"""catalog 모듈 Service — 비즈니스 로직 + ORM → 스키마 매핑.

- ORM 객체(Product)를 Pydantic 응답 스키마로 변환하는 책임.
- discount_pct / thumbnail_url 같은 계산 필드는 여기서 처리.
- DB 접근은 CatalogRepository 에 위임 (직접 session 호출 금지).
"""

from __future__ import annotations

from math import ceil

from app.catalog.catalog_repository import CatalogRepository
from app.catalog.catalog_schemas import (
    CATEGORY_META,
    CategoryMetaItem,
    ProductDetailResponse,
    ProductImageResponse,
    ProductListParams,
    ProductListResponse,
    ProductResponse,
)
from app.catalog.models import Product, ProductImage
from app.core.exceptions import ProductNotFound
from app.core.pagination import PageMeta


class CatalogService:
    def __init__(self, repo: CatalogRepository) -> None:
        self.repo = repo

    async def list_products(self, params: ProductListParams) -> ProductListResponse:
        products, total = await self.repo.get_list(params)
        meta = PageMeta(
            page=params.page,
            size=params.size,
            total=total,
            total_pages=ceil(total / params.size) if total else 0,
        )
        return ProductListResponse(
            items=[_to_response(p) for p in products],
            meta=meta,
        )

    async def get_product(self, product_id: int) -> ProductDetailResponse:
        product = await self.repo.get_by_id(product_id)
        if product is None:
            raise ProductNotFound()
        return _to_detail_response(product)

    async def get_featured(self, limit: int = 4) -> list[ProductResponse]:
        products = await self.repo.get_featured(limit)
        return [_to_response(p) for p in products]

    def get_categories(self) -> list[CategoryMetaItem]:
        return sorted(CATEGORY_META.values(), key=lambda c: c.sort_order)


# ── 내부 매핑 헬퍼 ───────────────────────────────────────────


def _thumbnail_url(product: Product) -> str | None:
    return product.images[0].url if product.images else None


def _discount_pct(product: Product) -> int | None:
    if not product.original_price or product.original_price <= 0:
        return None
    return round((1 - product.price / product.original_price) * 100)


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
