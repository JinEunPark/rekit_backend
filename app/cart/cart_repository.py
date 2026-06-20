"""cart 모듈 Repository — DB 접근 캡슐화."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.cart.models import CartItem
from app.catalog.models import Product


class CartRepository:
    """장바구니 DB 접근 객체. 모든 쿼리는 여기 모은다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_all_by_user_id(self, user_id: int) -> list[CartItem]:
        """사용자의 전체 장바구니 항목. 상품·이미지 eager load."""
        result = await self._session.execute(
            select(CartItem)
            .where(CartItem.user_id == user_id)
            .options(
                selectinload(CartItem.product).selectinload(Product.images)
            )
            .order_by(CartItem.id.asc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, item_id: int) -> CartItem | None:
        result = await self._session.execute(
            select(CartItem)
            .where(CartItem.id == item_id)
            .options(selectinload(CartItem.product).selectinload(Product.images))
        )
        return result.scalar_one_or_none()

    async def get_by_user_and_product(
        self, user_id: int, product_id: int
    ) -> CartItem | None:
        result = await self._session.execute(
            select(CartItem)
            .where(
                CartItem.user_id == user_id,
                CartItem.product_id == product_id,
            )
            .options(selectinload(CartItem.product).selectinload(Product.images))
        )
        return result.scalar_one_or_none()

    async def save(self, item: CartItem) -> CartItem:
        self._session.add(item)
        await self._session.flush()
        return item

    async def delete(self, item: CartItem) -> None:
        await self._session.delete(item)
        await self._session.flush()

    async def delete_by_ids(self, user_id: int, item_ids: list[int]) -> None:
        """user_id 조건 포함 — 타인의 항목을 실수로 삭제하지 않도록 보장."""
        await self._session.execute(
            delete(CartItem).where(
                CartItem.id.in_(item_ids),
                CartItem.user_id == user_id,
            )
        )

    async def get_product(self, product_id: int) -> Product | None:
        """상품 조회. add_item 에서 신규 담기 시 유효성 검증용.

        catalog_repository 를 주입하지 않고 cart_repository 가 직접 product 테이블을
        읽는 것이 모듈 간 결합도를 낮춘다 — CartRepository 는 cart 도메인의 단일 진입점.
        """
        result = await self._session.execute(
            select(Product)
            .where(Product.id == product_id)
            .options(selectinload(Product.images))
        )
        return result.scalar_one_or_none()
