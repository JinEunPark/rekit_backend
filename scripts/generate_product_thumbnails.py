"""기존 상품 이미지에 카드용 썸네일(긴 변 480px WebP)을 만들어 붙이는 1회성 백필 스크립트.

배경:
    카드(약 200px)·장바구니·주문 목록이 상세용 1600px 이미지(200~360KB)를 받고 있었다.
    새 업로드는 프론트가 썸네일을 함께 올리고 product_images.thumb_url 에 저장한다.
    이미 올라간 이미지는 thumb_url 이 NULL 이라 이 스크립트로 채운다
    (NULL 이어도 url 로 폴백되므로 급하지 않음).

동작:
    - stdin 으로 `id|url` 줄을 받는다 (psql -tA 출력 그대로). 운영 DB 는 외부에서 접속할 수 없어서
      DB 조회·갱신은 psql 로 하고, 이 스크립트는 스토리지와 SQL 생성만 담당한다.
    - 원본을 내려받아 EXIF 회전 반영 후 480px WebP 로 인코딩
      → `products/<이름>_thumb.webp` 로 업로드
    - stdout 으로 `UPDATE ... WHERE id = N AND thumb_url IS NULL;` 출력 (진행 로그는 stderr)
    - 기본은 dry-run(측정만, SQL 출력 없음). `--apply` 를 줘야 업로드하고 SQL 을 낸다.
      원본 이미지는 건드리지 않는다.

실행 (운영 예):
    Q="SELECT id, url FROM product_images WHERE thumb_url IS NULL ORDER BY id"
    ssh externalhost "docker exec rekle-postgres psql -U <user> -d <db> -tA -c \\"$Q\\"" \\
      | .venv/bin/python scripts/generate_product_thumbnails.py --apply > thumbs.sql
    ssh externalhost "docker exec -i rekle-postgres psql -U <user> -d <db>" < thumbs.sql

롤백:
    UPDATE product_images SET thumb_url = NULL;  (썸네일 객체는 남아도 무해)
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image, ImageOps

THUMB_EDGE = 480
THUMB_QUALITY = 80
PRODUCTS_PREFIX = "products/"


def key_from_url(url: str, public_base: str) -> str:
    base = public_base.rstrip("/") + "/"
    if not url.startswith(base):
        raise ValueError(f"스토리지 공개 URL 이 아님: {url}")
    return url[len(base) :]


def thumb_key_for(key: str) -> str:
    if not key.startswith(PRODUCTS_PREFIX):
        raise ValueError(f"상품 이미지 키가 아님: {key}")
    return key.rsplit(".", 1)[0] + "_thumb.webp"


def make_thumbnail(raw: bytes) -> bytes:
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
    im.thumbnail((THUMB_EDGE, THUMB_EDGE), Image.Resampling.LANCZOS)  # 작은 이미지는 키우지 않는다
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=THUMB_QUALITY, method=6)
    return buf.getvalue()


def update_sql(image_id: int, thumb_url: str) -> str:
    escaped = thumb_url.replace("'", "''")
    return (
        f"UPDATE product_images SET thumb_url = '{escaped}' "
        f"WHERE id = {image_id} AND thumb_url IS NULL;"
    )


def _parse(lines: list[str]) -> list[tuple[int, str]]:
    rows = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        image_id, url = line.split("|", 1)
        rows.append((int(image_id), url))
    return rows


async def main(apply: bool) -> None:
    from app.common.storage.s3_adapter import S3StorageAdapter
    from app.core.config import settings

    def log(msg: str) -> None:
        print(msg, file=sys.stderr)

    rows = _parse(sys.stdin.readlines())
    bucket = settings.s3_bucket
    base = settings.s3_public_url_base
    total_src = total_thumb = 0
    mode = "apply" if apply else "dry-run"
    log(f"{mode} · bucket={bucket} · {len(rows)} images\n")

    async with S3StorageAdapter()._client() as s3:
        for image_id, url in rows:
            try:
                key = key_from_url(url, base)
                thumb_key = thumb_key_for(key)
            except ValueError as e:
                log(f"SKIP  id={image_id}  ({e})")
                continue
            obj = await s3.get_object(Bucket=bucket, Key=key)
            raw = await obj["Body"].read()
            thumb = make_thumbnail(raw)
            total_src += len(raw)
            total_thumb += len(thumb)
            verb = "WRITE" if apply else "WOULD"
            log(f"{verb} id={image_id:<4} {key}  {len(raw):>9,} → {len(thumb):>7,} B  {thumb_key}")
            if apply:
                await s3.put_object(
                    Bucket=bucket, Key=thumb_key, Body=thumb, ContentType="image/webp"
                )
                print(update_sql(image_id, f"{base.rstrip('/')}/{thumb_key}"))

    if total_src:
        saved = (1 - total_thumb / total_src) * 100
        log(f"\n합계 {total_src:,} → {total_thumb:,} B  (-{saved:.1f}%)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--apply", action="store_true", help="업로드하고 UPDATE SQL 출력 (기본: dry-run)"
    )
    args = ap.parse_args()
    asyncio.run(main(args.apply))
