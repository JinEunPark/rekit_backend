"""스토리지에 이미 올라간 상품 이미지를 리사이즈·재압축해 같은 키에 덮어쓰는 1회성 스크립트.

배경:
    업로드가 presign(브라우저 → SeaweedFS 직접 PUT) 방식이라 서버가 본문을 손볼 지점이 없어,
    관리자가 올린 폰 원본(4000x3000, 2.5~3.9MB)이 그대로 카드 썸네일로 서빙됐다.
    프론트(rekit_client `src/utils/compressImage.ts`)가 이제 업로드 전에 줄이지만,
    기존 객체는 그대로라 이 스크립트로 한 번 정리한다.

동작:
    - `products/` 접두사 객체를 나열 → 긴 변 MAX_EDGE 로 축소, EXIF 회전 반영 후 재인코딩
    - **키·확장자·Content-Type 은 유지** (.jpg → JPEG) → DB 의 product_images.url 은 손대지 않는다
    - 덮어쓰기 전 원본을 `backup/originals/<key>` 로 복사.
      백업이 이미 있으면 처리된 것으로 보고 건너뜀(멱등)
    - 기본은 dry-run(측정만). `--apply` 를 줘야 실제로 쓴다.

실행:
    .venv/bin/pip install -e '.[scripts]'          # Pillow
    .venv/bin/python scripts/recompress_product_images.py            # dry-run
    .venv/bin/python scripts/recompress_product_images.py --apply    # 실제 덮어쓰기

롤백:
    backup/originals/products/<name> 을 products/<name> 으로 다시 복사하면 된다.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image, ImageOps

MAX_EDGE = 1600
QUALITY = 82
SKIP_BELOW_BYTES = 500 * 1024
BACKUP_PREFIX = "backup/originals/"

FORMAT_BY_EXT = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}
CONTENT_TYPE_BY_FORMAT = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


@dataclass
class Result:
    data: bytes | None  # None = 건너뜀
    size: tuple[int, int]
    reason: str = ""


def recompress(raw: bytes, ext: str) -> Result:
    """순수 변환 함수 — 스토리지와 무관하게 테스트할 수 있도록 분리."""
    fmt = FORMAT_BY_EXT.get(ext.lower())
    if fmt is None:
        return Result(None, (0, 0), f"지원하지 않는 확장자 {ext}")
    im = Image.open(io.BytesIO(raw))
    if len(raw) < SKIP_BELOW_BYTES and max(im.size) <= MAX_EDGE:
        return Result(None, im.size, "이미 작음")

    im = ImageOps.exif_transpose(im)  # orientation=6 세로 사진을 픽셀로 회전 (EXIF 는 버린다)
    im.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    if fmt == "JPEG":
        im.convert("RGB").save(buf, "JPEG", quality=QUALITY, optimize=True, progressive=True)
    elif fmt == "WEBP":
        im.save(buf, "WEBP", quality=QUALITY, method=6)
    else:
        im.save(buf, "PNG", optimize=True)
    out = buf.getvalue()
    if len(out) >= len(raw):
        return Result(None, im.size, "재압축해도 커짐")
    return Result(out, im.size)


async def main(apply: bool, prefix: str) -> None:
    from botocore.exceptions import ClientError

    from app.common.storage.s3_adapter import S3StorageAdapter
    from app.core.config import settings

    bucket = settings.s3_bucket
    adapter = S3StorageAdapter()
    total_before = total_after = done = skipped = 0

    async with adapter._client() as s3:
        keys: list[str] = []
        paginator = s3.get_paginator("list_objects_v2")
        async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            keys += [o["Key"] for o in page.get("Contents", [])]

        mode = "apply" if apply else "dry-run"
        print(f"{mode} · bucket={bucket} · prefix={prefix} · {len(keys)} objects\n")
        for key in sorted(keys):
            backup_key = BACKUP_PREFIX + key
            try:
                await s3.head_object(Bucket=bucket, Key=backup_key)
                print(f"SKIP  {key}  (백업 존재 — 이미 처리됨)")
                skipped += 1
                continue
            except ClientError:
                pass

            obj = await s3.get_object(Bucket=bucket, Key=key)
            raw = await obj["Body"].read()
            res = recompress(raw, key.rsplit(".", 1)[-1])
            if res.data is None:
                print(f"SKIP  {key}  {len(raw):>10,} B  ({res.reason})")
                skipped += 1
                continue

            total_before += len(raw)
            total_after += len(res.data)
            done += 1
            pct = (1 - len(res.data) / len(raw)) * 100
            verb = "WRITE" if apply else "WOULD"
            dims = f"{res.size[0]}x{res.size[1]}"
            print(f"{verb} {key}  {len(raw):>10,} → {len(res.data):>8,} B  (-{pct:.1f}%)  {dims}")

            if apply:
                await s3.copy_object(
                    Bucket=bucket, Key=backup_key, CopySource={"Bucket": bucket, "Key": key}
                )
                fmt = FORMAT_BY_EXT[key.rsplit(".", 1)[-1].lower()]
                await s3.put_object(
                    Bucket=bucket, Key=key, Body=res.data, ContentType=CONTENT_TYPE_BY_FORMAT[fmt]
                )

    print(f"\n처리 {done} · 건너뜀 {skipped}")
    if done:
        saved = (1 - total_after / total_before) * 100
        print(f"합계 {total_before:,} → {total_after:,} B  (-{saved:.1f}%)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--apply", action="store_true", help="실제로 덮어쓴다 (기본: dry-run)")
    ap.add_argument("--prefix", default="products/")
    args = ap.parse_args()
    asyncio.run(main(args.apply, args.prefix))
