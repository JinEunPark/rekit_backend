"""payment 모듈 Repository — DB 접근 캡슐화."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

    async def get_by_pg_tid(self, pg_tid: str) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(Payment.pg_tid == pg_tid)
        )
        return result.scalar_one_or_none()

    async def get_order_by_number(self, order_number: str) -> Order | None:
        result = await self._session.execute(
            select(Order).where(Order.order_number == order_number)
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
