"""payment 모듈 Repository — DB 접근 캡슐화."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.catalog.catalog_utils import stock_increment_status_case
from app.catalog.models import Product
from app.order.models import Order, OrderStatus
from app.payment.adapters.ports import TossConfirmResult
from app.payment.models import Payment, PaymentStatus
from app.user.models import User


class PaymentRepository:
    """결제 DB 접근 객체. 모든 쿼리는 여기 모은다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, payment_id: int) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(Payment.id == payment_id)
        )
        return result.scalar_one_or_none()

    async def get_by_order_id(self, order_id: int) -> list[Payment]:
        result = await self._session.execute(
            select(Payment).where(Payment.order_id == order_id)
        )
        return list(result.scalars().all())

    async def get_by_order_id_with_lock(self, order_id: int) -> list[Payment]:
        """FOR UPDATE 락으로 결제 목록 조회 — 동시 confirm 이중 호출 방지."""
        result = await self._session.execute(
            select(Payment).where(Payment.order_id == order_id).with_for_update()
        )
        return list(result.scalars().all())

    async def get_by_pg_tid(self, pg_tid: str) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(Payment.pg_tid == pg_tid)
        )
        return result.scalar_one_or_none()

    async def get_by_pg_tid_with_lock(self, pg_tid: str) -> Payment | None:
        """SELECT FOR UPDATE 로 Payment 조회 — 웹훅 동시 수신 경쟁 방지."""
        result = await self._session.execute(
            select(Payment).where(Payment.pg_tid == pg_tid).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_ready_payment_by_order_number(self, order_number: str) -> Payment | None:
        """order_number로 주문을 찾아 READY 상태 결제 반환 (웹훅 pg_tid 없을 때 fallback)."""
        order_result = await self._session.execute(
            select(Order).where(Order.order_number == order_number)
        )
        order = order_result.scalar_one_or_none()
        if order is None:
            return None
        payment_result = await self._session.execute(
            select(Payment).where(
                Payment.order_id == order.id,
                Payment.status == PaymentStatus.READY,
            )
        )
        return payment_result.scalar_one_or_none()

    async def get_ready_payment_by_order_number_with_lock(
        self, order_number: str
    ) -> Payment | None:
        """order_number로 READY Payment를 SELECT FOR UPDATE 조회 (pg_tid 없는 fallback 경로 락)."""
        order_result = await self._session.execute(
            select(Order).where(Order.order_number == order_number)
        )
        order = order_result.scalar_one_or_none()
        if order is None:
            return None
        payment_result = await self._session.execute(
            select(Payment)
            .where(
                Payment.order_id == order.id,
                Payment.status == PaymentStatus.READY,
            )
            .with_for_update()
        )
        return payment_result.scalar_one_or_none()

    async def get_order_by_number(self, order_number: str) -> Order | None:
        result = await self._session.execute(
            select(Order).where(Order.order_number == order_number)
        )
        return result.scalar_one_or_none()

    async def get_order_by_number_with_lock(self, order_number: str) -> Order | None:
        """FOR UPDATE 락으로 주문 조회 — init_payment에서 READY 확인+생성을 원자적으로 처리."""
        result = await self._session.execute(
            select(Order).where(Order.order_number == order_number).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_order_by_id(self, order_id: int) -> Order | None:
        result = await self._session.execute(
            select(Order).where(Order.id == order_id).options(selectinload(Order.items))
        )
        return result.scalar_one_or_none()

    async def get_order_by_id_with_lock(self, order_id: int) -> Order | None:
        """SELECT FOR UPDATE 로 Order 조회 (아이템 포함) — 웹훅 취소 시 재고 이중 복구 방지."""
        result = await self._session.execute(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update()
            .options(selectinload(Order.items))
        )
        return result.scalar_one_or_none()

    async def save(self, payment: Payment) -> Payment:
        """DB 에 추가 후 flush 로 PK 할당. commit 은 deps.db_session 에서."""
        self._session.add(payment)
        await self._session.flush()
        await self._session.refresh(payment)
        return payment

    async def update_status_paid(
        self, payment: Payment, result: TossConfirmResult
    ) -> None:
        """confirm 성공 후 PAID 상태로 전환 + PG 메타데이터 저장."""
        payment.status = PaymentStatus.PAID
        payment.pg_tid = result.pg_tid
        payment.paid_at = result.paid_at
        payment.card_company = result.card_company
        payment.card_last4 = result.card_last4
        payment.installment_months = result.installment_months
        payment.approval_number = result.approval_number
        await self._session.flush()

    async def get_user_email(self, user_id: int) -> str | None:
        result = await self._session.execute(
            select(User.email).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def update_order_paid(self, order: Order) -> None:
        """주문 상태를 PAID 로 전환 + paid_at 기록."""
        order.status = OrderStatus.PAID
        order.paid_at = datetime.now(UTC)
        await self._session.flush()

    async def increment_stock(self, product_id: int, quantity: int) -> None:
        """재고를 quantity 만큼 가산 (결제 실패/취소 웹훅 시 복구용). 원자적 UPDATE.

        재고가 0 을 넘고 현재 SOLD_OUT 이면 ACTIVE 로 자동 복원한다.
        운영자가 수동으로 INACTIVE 처리한 상품은 대상에서 제외한다.
        """
        new_stock = Product.stock + quantity
        stmt = (
            update(Product)
            .where(Product.id == product_id)
            .values(stock=new_stock, status=stock_increment_status_case(new_stock))
        )
        await self._session.execute(stmt)
