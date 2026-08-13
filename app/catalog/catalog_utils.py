"""catalog 공용 계산 헬퍼 — discount_pct · thumbnail_url · 재고 증감 시 status 자동 전환.

discount_pct/thumbnail_url 은 CatalogService / AdminCatalogService / FavoritesService
3곳에서, stock_decrement_status_case/stock_increment_status_case 는 order/admin_order/
payment 의 각 Repository 가 동일하게 사용한다 — 재고-상태 전환 규칙은 여기 한 곳에서만
정의해 여러 Repository 에 SQL 이 복제되지 않게 한다.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, and_, case

from app.catalog.models import Product, ProductStatus


def discount_pct(product: Product) -> int | None:
    if not product.original_price or product.original_price <= 0:
        return None
    return round((1 - product.price / product.original_price) * 100)


def thumbnail_url(product: Product) -> str | None:
    return product.images[0].url if product.images else None


def stock_decrement_status_case(new_stock: ColumnElement[int]) -> ColumnElement[ProductStatus]:
    """재고 감산 후 값이 0 이하면 ACTIVE → SOLD_OUT, 그 외엔 기존 status 유지."""
    return case(
        (
            and_(new_stock <= 0, Product.status == ProductStatus.ACTIVE),
            ProductStatus.SOLD_OUT,
        ),
        else_=Product.status,
    )


def stock_increment_status_case(new_stock: ColumnElement[int]) -> ColumnElement[ProductStatus]:
    """재고 가산 후 값이 0 초과면 SOLD_OUT → ACTIVE 로 복원, 그 외엔 기존 status 유지.

    운영자가 수동으로 INACTIVE 처리한 상품은 대상에서 제외한다.
    """
    return case(
        (
            and_(new_stock > 0, Product.status == ProductStatus.SOLD_OUT),
            ProductStatus.ACTIVE,
        ),
        else_=Product.status,
    )
