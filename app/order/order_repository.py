"""order 모듈 Repository — orders / order_items 테이블 접근.

- service 만 호출. router 직접 호출 금지 (CLAUDE.md 모듈 규칙).
- 재고 차감은 SELECT … FOR UPDATE 락 후 UPDATE 로 처리 (동시 주문 경쟁 조건 방지).
- 이미지/아이템은 selectinload 로 N+1 방지.
"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.address.models import Address
from app.catalog.models import Product
from app.order.models import Order, OrderItem  # noqa: F401 — OrderItem used by relationship


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_list_by_user(
        self, user_id: int, page: int, size: int
    ) -> tuple[list[Order], int]:
        """user_id 소유 주문 목록 (최신순, 페이지네이션). (items, total) 반환."""
        base = select(Order).where(Order.user_id == user_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total: int = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            base.order_by(Order.created_at.desc(), Order.id.desc())
            .offset((page - 1) * size)
            .limit(size)
            .options(selectinload(Order.items))
        )
        result = await self._session.execute(stmt)
        return list(result.scalars()), total

    async def get_by_order_number(self, order_number: str) -> Order | None:
        """order_number 로 주문 단건 조회 (아이템 포함). 없으면 None."""
        stmt = (
            select(Order)
            .where(Order.order_number == order_number)
            .options(selectinload(Order.items))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_order_number_with_shipment(self, order_number: str) -> Order | None:
        """order_number 로 주문 단건 조회 (shipment 포함, items 제외). get_shipment 전용."""
        stmt = (
            select(Order)
            .where(Order.order_number == order_number)
            .options(selectinload(Order.shipment))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_product(self, product_id: int) -> Product | None:
        """락 없는 단건 상품 조회. get_quote 같은 read-only 경로용."""
        stmt = (
            select(Product)
            .where(Product.id == product_id)
            .options(selectinload(Product.images))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_product_with_lock(self, product_id: int) -> Product | None:
        """SELECT … FOR UPDATE 로 상품 단건 조회 (재고 갱신 직전 락)."""
        stmt = (
            select(Product)
            .where(Product.id == product_id)
            .with_for_update()
            .options(selectinload(Product.images))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_products_with_lock(
        self, product_ids: list[int]
    ) -> dict[int, Product]:
        """N개 상품을 WHERE id IN (...) FOR UPDATE 한 번에 조회.

        create_order 에서 순차 락 대신 사용 — 쿼리 수 O(N)→O(1).
        반환: {product_id: Product} — 없는 id 는 포함되지 않음.
        """
        stmt = (
            select(Product)
            .where(Product.id.in_(product_ids))
            .with_for_update()
            .options(selectinload(Product.images))
        )
        result = await self._session.execute(stmt)
        return {p.id: p for p in result.scalars()}

    async def get_address_by_id(self, address_id: int) -> Address | None:
        """address_id 단건 조회 (소유권 확인 없음). 존재 여부만 확인할 때 사용."""
        stmt = select(Address).where(Address.id == address_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_address_by_user(self, user_id: int, address_id: int) -> Address | None:
        """user_id + address_id 로 배송지 조회. 소유권 확인 포함."""
        stmt = select(Address).where(
            Address.id == address_id,
            Address.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def save(self, order: Order) -> Order:
        """Order 를 세션에 추가하고 flush 해 PK 를 즉시 확보한다.

        commit 은 `app.core.deps.db_session` 의 컨텍스트 관리자가 담당한다.
        """
        self._session.add(order)
        await self._session.flush()
        return order

    async def update_order_number(self, order: Order, order_number: str) -> None:
        """flush 된 Order 의 order_number 를 PK 기반 번호로 교체한다.

        commit 전이므로 flush 는 불필요 — commit 시 반영된다.
        """
        order.order_number = order_number

    async def decrement_stock(self, product_id: int, quantity: int) -> None:
        """재고를 quantity 만큼 감산 (SQL UPDATE — Python 루프 없이 원자적 처리)."""
        stmt = (
            update(Product)
            .where(Product.id == product_id)
            .values(stock=Product.stock - quantity)
        )
        await self._session.execute(stmt)
