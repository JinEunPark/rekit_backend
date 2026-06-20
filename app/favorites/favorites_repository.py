from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.catalog.models import Product, ProductImage
from app.favorites.models import Favorite


class FavoritesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_all_by_user_id(self, user_id: int) -> list[Favorite]:
        stmt = (
            select(Favorite)
            .where(Favorite.user_id == user_id)
            .options(
                selectinload(Favorite.product).selectinload(Product.images)
            )
            .order_by(Favorite.user_id, Favorite.product_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def get_by_user_and_product(
        self, user_id: int, product_id: int
    ) -> Favorite | None:
        stmt = select(Favorite).where(
            Favorite.user_id == user_id,
            Favorite.product_id == product_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def save(self, favorite: Favorite) -> Favorite:
        self.session.add(favorite)
        await self.session.flush()
        return favorite

    async def delete(self, favorite: Favorite) -> None:
        await self.session.delete(favorite)
