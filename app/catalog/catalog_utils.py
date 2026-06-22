"""catalog 공용 계산 헬퍼 — discount_pct · thumbnail_url.

CatalogService / AdminCatalogService / FavoritesService 3곳에서 동일하게 사용.
"""

from __future__ import annotations

from app.catalog.models import Product


def discount_pct(product: Product) -> int | None:
    if not product.original_price or product.original_price <= 0:
        return None
    return round((1 - product.price / product.original_price) * 100)


def thumbnail_url(product: Product) -> str | None:
    return product.images[0].url if product.images else None
