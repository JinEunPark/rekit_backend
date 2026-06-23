"""favorites service 단위 테스트.

DB 없이 fake repo + in-memory Favorite/Product 객체로 도메인 로직 검증.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.catalog.models import ConditionGrade, Product, ProductImage, ProductStatus
from app.core.exceptions import FavoriteNotFound
from app.favorites.favorites_schemas import FavoriteToggleResponse
from app.favorites.favorites_service import FavoritesService
from app.favorites.models import Favorite


# ── 팩토리 ─────────────────────────────────────────────────────


def make_product(
    *,
    product_id: int = 1,
    price: int = 300_000,
    original_price: int | None = 500_000,
    images: list[ProductImage] | None = None,
) -> Product:
    p = Product(
        title="테스트 냉장고",
        description="",
        category="REFRIGERATOR",
        condition_grade=ConditionGrade.A,
        warranty_works=True,
        price=price,
        original_price=original_price,
        stock=1,
        status=ProductStatus.ACTIVE,
    )
    p.id = product_id
    p.created_at = datetime.now(UTC)
    for img in images or []:
        p.images.append(img)
    return p


def make_image(*, url: str = "https://cdn.example.com/img.jpg") -> ProductImage:
    img = ProductImage(url=url, sort_order=0)
    img.id = 1
    return img


def make_favorite(*, user_id: int = 1, product: Product) -> Favorite:
    fav = Favorite(user_id=user_id, product_id=product.id)
    fav.product = product
    fav.created_at = datetime.now(UTC)
    return fav


# ── Fake repo ───────────────────────────────────────────────────


class _FakeFavoritesRepo:
    def __init__(self, favorites: list[Favorite] | None = None) -> None:
        self._favorites: list[Favorite] = list(favorites or [])

    async def get_all_by_user_id(self, user_id: int) -> list[Favorite]:
        return [f for f in self._favorites if f.user_id == user_id]

    async def get_by_user_and_product(self, user_id: int, product_id: int) -> Favorite | None:
        return next(
            (f for f in self._favorites if f.user_id == user_id and f.product_id == product_id),
            None,
        )

    async def save(self, favorite: Favorite) -> Favorite:
        self._favorites.append(favorite)
        return favorite

    async def delete(self, favorite: Favorite) -> None:
        self._favorites.remove(favorite)


def _make_service(favorites: list[Favorite] | None = None) -> FavoritesService:
    return FavoritesService(_FakeFavoritesRepo(favorites))  # type: ignore[arg-type]


# ── 테스트 ──────────────────────────────────────────────────────


async def test_list_favorites_empty() -> None:
    service = _make_service()
    result = await service.list_favorites(user_id=1)
    assert result == []


async def test_list_favorites_returns_items() -> None:
    p = make_product(product_id=1)
    fav = make_favorite(user_id=1, product=p)
    service = _make_service([fav])

    result = await service.list_favorites(user_id=1)

    assert len(result) == 1
    assert result[0].product_id == 1


async def test_list_favorites_isolates_by_user() -> None:
    p = make_product(product_id=1)
    service = _make_service([
        make_favorite(user_id=1, product=p),
        make_favorite(user_id=2, product=p),
    ])

    result = await service.list_favorites(user_id=1)

    assert len(result) == 1


async def test_add_favorite_creates_new() -> None:
    service = _make_service()
    result = await service.add_favorite(user_id=1, product_id=42)

    assert isinstance(result, FavoriteToggleResponse)
    assert result.product_id == 42
    assert result.is_favorite is True


async def test_add_favorite_idempotent() -> None:
    """이미 추가된 관심상품 재등록 → 에러 없이 is_favorite=True."""
    p = make_product(product_id=5)
    service = _make_service([make_favorite(user_id=1, product=p)])

    result = await service.add_favorite(user_id=1, product_id=5)

    assert result.is_favorite is True


async def test_remove_favorite_success() -> None:
    p = make_product(product_id=3)
    fav = make_favorite(user_id=1, product=p)
    service = _make_service([fav])

    result = await service.remove_favorite(user_id=1, product_id=3)

    assert result.is_favorite is False
    assert await service.list_favorites(user_id=1) == []


async def test_remove_favorite_not_found_raises() -> None:
    with pytest.raises(FavoriteNotFound):
        await _make_service().remove_favorite(user_id=1, product_id=999)


async def test_discount_pct_computed() -> None:
    p = make_product(price=300_000, original_price=500_000)
    service = _make_service([make_favorite(user_id=1, product=p)])

    result = await service.list_favorites(user_id=1)

    assert result[0].discount_pct == 40


async def test_discount_pct_null_without_original_price() -> None:
    p = make_product(original_price=None)
    service = _make_service([make_favorite(user_id=1, product=p)])

    result = await service.list_favorites(user_id=1)

    assert result[0].discount_pct is None


async def test_thumbnail_url_from_first_image() -> None:
    img = make_image(url="https://cdn.example.com/front.jpg")
    p = make_product(images=[img])
    service = _make_service([make_favorite(user_id=1, product=p)])

    result = await service.list_favorites(user_id=1)

    assert result[0].thumbnail_url == "https://cdn.example.com/front.jpg"


async def test_thumbnail_url_null_when_no_images() -> None:
    p = make_product(images=[])
    service = _make_service([make_favorite(user_id=1, product=p)])

    result = await service.list_favorites(user_id=1)

    assert result[0].thumbnail_url is None
