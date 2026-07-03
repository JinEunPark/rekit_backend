from __future__ import annotations

from app.catalog.catalog_utils import discount_pct as _discount_pct
from app.catalog.catalog_utils import thumbnail_url as _thumbnail_url
from app.core.exceptions import FavoriteNotFoundError
from app.favorites.favorites_repository import FavoritesRepository
from app.favorites.favorites_schemas import FavoriteProductItem, FavoriteToggleResponse
from app.favorites.models import Favorite


class FavoritesService:
    def __init__(self, repo: FavoritesRepository) -> None:
        self._repo = repo

    async def list_favorites(self, user_id: int) -> list[FavoriteProductItem]:
        favorites = await self._repo.get_all_by_user_id(user_id)
        return [_to_item(f) for f in favorites]

    async def add_favorite(
        self, user_id: int, product_id: int
    ) -> FavoriteToggleResponse:
        existing = await self._repo.get_by_user_and_product(user_id, product_id)
        if existing is None:
            fav = Favorite(user_id=user_id, product_id=product_id)
            await self._repo.save(fav)
        return FavoriteToggleResponse(product_id=product_id, is_favorite=True)

    async def remove_favorite(
        self, user_id: int, product_id: int
    ) -> FavoriteToggleResponse:
        fav = await self._repo.get_by_user_and_product(user_id, product_id)
        if fav is None:
            raise FavoriteNotFoundError()
        await self._repo.delete(fav)
        return FavoriteToggleResponse(product_id=product_id, is_favorite=False)


def _to_item(fav: Favorite) -> FavoriteProductItem:
    p = fav.product
    return FavoriteProductItem(
        product_id=p.id,
        title=p.title,
        price=p.price,
        original_price=p.original_price,
        discount_pct=_discount_pct(p),
        thumbnail_url=_thumbnail_url(p),
        category=p.category,
        condition_grade=p.condition_grade,
        warranty_works=p.warranty_works,
        added_at=fav.created_at,
    )
