"""catalog 모듈 Service — 비즈니스 로직 + ORM → 스키마 매핑.

- ORM 객체(Product)를 Pydantic 응답 스키마로 변환하는 책임.
- discount_pct / thumbnail_url 같은 계산 필드는 여기서 처리.
- DB 접근은 CatalogRepository 에 위임 (직접 session 호출 금지).
"""

from __future__ import annotations

from app.catalog.catalog_repository import CatalogRepository
from app.catalog.catalog_schemas import (
    CategoryMetaItem,
    ProductDetailResponse,
    ProductImageResponse,
    ProductListParams,
    ProductListResponse,
    ProductResponse,
)
from app.catalog.catalog_utils import discount_pct as _discount_pct
from app.catalog.catalog_utils import thumbnail_url as _thumbnail_url
from app.catalog.models import Product, ProductImage
from app.core.exceptions import ProductNotFound
from app.core.pagination import build_page_meta


class CatalogService:
    def __init__(self, repo: CatalogRepository) -> None:
        self.repo = repo

    async def list_products(self, params: ProductListParams) -> ProductListResponse:
        products, total = await self.repo.get_list(params)
        return ProductListResponse(
            items=[_to_response(p) for p in products],
            meta=build_page_meta(total, params.page, params.size),
        )

    async def get_product(self, product_id: int) -> ProductDetailResponse:
        product = await self.repo.get_by_id(product_id)
        if product is None:
            raise ProductNotFound()
        return _to_detail_response(product)

    async def get_featured(self, limit: int = 4) -> list[ProductResponse]:
        products = await self.repo.get_featured(limit)
        return [_to_response(p) for p in products]

    async def get_products_by_ids(self, ids: list[int]) -> list[ProductResponse]:
        products = await self.repo.get_by_ids(ids)
        return [_to_response(p) for p in products]

    async def get_categories(self) -> list[CategoryMetaItem]:
        cats = await self.repo.get_categories()
        return [
            CategoryMetaItem(id=c.id, label=c.title, icon=c.icon, sort_order=c.sort_order)
            for c in cats
        ]


# ── 내부 매핑 헬퍼 ───────────────────────────────────────────


def _to_image(image: ProductImage) -> ProductImageResponse:
    return ProductImageResponse(
        id=image.id,
        url=image.url,
        sort_order=image.sort_order,
        label=image.label,
    )


def _to_response(product: Product) -> ProductResponse:
    return ProductResponse(
        id=product.id,
        title=product.title,
        category=product.category,
        brand=product.brand,
        condition_grade=product.condition_grade,
        warranty_works=product.warranty_works,
        price=product.price,
        original_price=product.original_price,
        discount_pct=_discount_pct(product),
        status=product.status,
        thumbnail_url=_thumbnail_url(product),
        created_at=product.created_at,
    )


def _to_detail_response(product: Product) -> ProductDetailResponse:
    return ProductDetailResponse(
        id=product.id,
        title=product.title,
        category=product.category,
        brand=product.brand,
        condition_grade=product.condition_grade,
        warranty_works=product.warranty_works,
        price=product.price,
        original_price=product.original_price,
        discount_pct=_discount_pct(product),
        status=product.status,
        thumbnail_url=_thumbnail_url(product),
        created_at=product.created_at,
        description=product.description,
        model_name=product.model_name,
        year_estimate=product.year_estimate,
        weight_kg=product.weight_kg,
        width_cm=product.width_cm,
        depth_cm=product.depth_cm,
        height_cm=product.height_cm,
        stock=product.stock,
        images=[_to_image(img) for img in product.images],
    )
