"""상품 이미지를 SeaweedFS 에 업로드하고 DB URL 을 교체하는 스크립트.

실행:
    .venv/bin/python scripts/upload_images_to_seaweedfs.py

동작:
1. 상품 타입별 Unsplash 이미지를 다운로드
2. SeaweedFS 에 PUT 업로드
3. product_images 레코드를 SeaweedFS public URL 로 교체
4. 이미지 없는 상품에도 적절한 이미지 삽입
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import aioboto3
from aiobotocore.config import AioConfig
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import app.db.registry  # noqa: F401
from app.core.config import settings
from app.catalog.models import Product, ProductImage

engine = create_async_engine(settings.database_url, echo=False)

# ── 상품별 이미지 URL 정의 ──────────────────────────────────────────
# Unsplash 직접 다운로드 URL (무료, 저작권 없음)
PRODUCT_IMAGES: dict[int, list[str]] = {
    1: [  # LG 냉장고
        "https://images.unsplash.com/photo-1571175443880-49e1d25b2bc5?w=800&q=80",
        "https://images.unsplash.com/photo-1584568694244-14fbdf83bd30?w=800&q=80",
    ],
    2: [  # 삼성 드럼세탁기
        "https://images.unsplash.com/photo-1626806787461-102c1bfaaea1?w=800&q=80",
        "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=800&q=80",
    ],
    3: [  # LG 올레드 TV
        "https://images.unsplash.com/photo-1593359677879-a4bb92f829d1?w=800&q=80",
        "https://images.unsplash.com/photo-1567690187548-f07b1d7bf5a9?w=800&q=80",
    ],
    4: [  # 캐리어 에어컨
        "https://images.unsplash.com/photo-1585771724684-38269d6639fd?w=800&q=80",
        "https://images.unsplash.com/photo-1558618047-3c8c76ca7d13?w=800&q=80",
    ],
    5: [  # 삼성 김치냉장고
        "https://images.unsplash.com/photo-1584568694244-14fbdf83bd30?w=800&q=80",
        "https://images.unsplash.com/photo-1571175443880-49e1d25b2bc5?w=800&q=80",
    ],
    6: [  # 다이슨 청소기
        "https://images.unsplash.com/photo-1558317374-067fb5f30001?w=800&q=80",
        "https://images.unsplash.com/photo-1527515637462-cff94aca208b?w=800&q=80",
    ],
    # 테스트 전자레인지 (id 10-13)
    10: ["https://images.unsplash.com/photo-1574269909862-7e1d70bb8078?w=800&q=80"],
    11: ["https://images.unsplash.com/photo-1574269909862-7e1d70bb8078?w=800&q=80"],
    12: ["https://images.unsplash.com/photo-1574269909862-7e1d70bb8078?w=800&q=80"],
    13: ["https://images.unsplash.com/photo-1574269909862-7e1d70bb8078?w=800&q=80"],
    # 테스트 냉장고 (id 14-17, 19)
    14: ["https://images.unsplash.com/photo-1571175443880-49e1d25b2bc5?w=800&q=80"],
    15: ["https://images.unsplash.com/photo-1571175443880-49e1d25b2bc5?w=800&q=80"],
    16: ["https://images.unsplash.com/photo-1571175443880-49e1d25b2bc5?w=800&q=80"],
    17: ["https://images.unsplash.com/photo-1571175443880-49e1d25b2bc5?w=800&q=80"],
    19: ["https://images.unsplash.com/photo-1571175443880-49e1d25b2bc5?w=800&q=80"],
    # 결제테스트 세탁기 (id 18, 20)
    18: ["https://images.unsplash.com/photo-1626806787461-102c1bfaaea1?w=800&q=80"],
    20: ["https://images.unsplash.com/photo-1626806787461-102c1bfaaea1?w=800&q=80"],
}

EXT_MAP = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


async def download_image(url: str, client: httpx.AsyncClient) -> tuple[bytes, str]:
    """URL 에서 이미지 다운로드. (bytes, content_type) 반환."""
    resp = await client.get(url, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    if content_type not in ("image/jpeg", "image/png", "image/webp"):
        content_type = "image/jpeg"
    return resp.content, content_type


async def _process_one(
    *,
    product_id: int,
    sort_order: int,
    img_url: str,
    http_client: httpx.AsyncClient,
    s3: object,
    sem: asyncio.Semaphore,
) -> ProductImage | None:
    """이미지 1장을 다운로드 → SeaweedFS 업로드 → ProductImage 객체 반환."""
    async with sem:
        try:
            data, content_type = await download_image(img_url, http_client)
            ext = EXT_MAP.get(content_type, "jpg")
            key = f"products/{uuid4()}.{ext}"
            await s3.put_object(  # type: ignore[attr-defined]
                Bucket=settings.s3_bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
            public_url = f"{settings.s3_public_url_base.rstrip('/')}/{key}"
            print(f"  [ok] id={product_id} [{sort_order}] {key} ({len(data) // 1024}KB)")
            return ProductImage(product_id=product_id, url=public_url, sort_order=sort_order)
        except Exception as exc:
            print(f"  [err] id={product_id} [{sort_order}] {exc}")
            return None


async def main() -> None:
    print("=== SeaweedFS 이미지 업로드 시작 ===\n")

    # 동시 요청 수 제한 (Unsplash + SeaweedFS 과부하 방지)
    sem = asyncio.Semaphore(5)

    session_s3 = aioboto3.Session()
    async with httpx.AsyncClient(headers={"User-Agent": "rekle-seed/1.0"}) as http_client:
        async with session_s3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=AioConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        ) as s3:
            async with AsyncSession(engine) as session:
                async with session.begin():
                    await session.execute(text("DELETE FROM product_images"))
                    print("[1] 기존 product_images 전부 삭제\n")

                    products = list(
                        (await session.execute(select(Product).order_by(Product.id))).scalars()
                    )

                    print("[2] 이미지 다운로드 → SeaweedFS 업로드 (병렬)")

                    tasks = []
                    for product in products:
                        urls = PRODUCT_IMAGES.get(product.id)
                        if not urls:
                            print(f"  [skip] id={product.id} — 이미지 정의 없음")
                            continue
                        for sort_order, img_url in enumerate(urls):
                            tasks.append(
                                _process_one(
                                    product_id=product.id,
                                    sort_order=sort_order,
                                    img_url=img_url,
                                    http_client=http_client,
                                    s3=s3,
                                    sem=sem,
                                )
                            )

                    results = await asyncio.gather(*tasks)
                    images = [img for img in results if img is not None]

                    for img in images:
                        session.add(img)

                    await session.flush()

    await engine.dispose()
    print(f"\n=== 완료 ({len(images)}장) ===")
    print(f"클라이언트 이미지 베이스 URL: {settings.s3_public_url_base}")


if __name__ == "__main__":
    asyncio.run(main())
