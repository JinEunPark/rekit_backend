"""방치 주문 스위퍼 통합 테스트 — 실제 Postgres 의 SKIP LOCKED / 트랜잭션 경계 검증.

개발 DB 의 실제 PENDING 주문을 건드리지 않도록 테스트 주문은 2000년에 만든 것으로 두고,
스윕 기준 시각(now)도 그 시점으로 넘겨 테스트 데이터만 대상이 되게 한다.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import ConditionGrade, Product, ProductStatus
from app.core.database import async_session_factory
from app.core.exceptions import PaymentGatewayUnknownError
from app.order.abandoned_order_sweeper import sweep_abandoned_orders
from app.order.models import Order, OrderItem, OrderStatus
from app.order.shipment import ShipmentMethod
from app.payment.models import Payment, PaymentMethod, PaymentStatus, PgProvider
from app.user.models import User

_BASE = datetime(2000, 1, 1, tzinfo=UTC)
_NOW = _BASE + timedelta(hours=1)


class _Gateway:
    """orderId 조회만 쓰는 스텁. unknown 에 든 주문은 조회 실패를 흉내낸다."""

    def __init__(self, *, unknown: set[str] | None = None) -> None:
        self.unknown = unknown or set()
        self.lookups: list[str] = []

    async def get_payment_by_order_id(self, *, order_id: str) -> None:
        self.lookups.append(order_id)
        if order_id in self.unknown:
            raise PaymentGatewayUnknownError()


class _NoopEmailSender:
    async def send(self, *, to: str, subject: str, body: str, **_: object) -> None:
        del to, subject, body


async def _seed(
    session: AsyncSession, *, tag: str, specs: list[tuple[timedelta, bool]]
) -> tuple[int, list[str]]:
    """재고 0 상품 + (경과시간, READY 결제 여부) 별 PENDING 주문(각 1개씩 재고 점유)."""
    user = (await session.execute(select(User).limit(1))).scalars().first()
    assert user is not None, "테스트 대상 DB에 최소 1명의 User 가 있어야 함"
    product = Product(
        title="스위퍼 테스트 상품", category="ETC", condition_grade=ConditionGrade.B,
        price=10_000, stock=0, status=ProductStatus.SOLD_OUT,
    )
    session.add(product)
    await session.flush()
    numbers: list[str] = []
    for i, (age, with_ready) in enumerate(specs):
        order = Order(
            order_number=f"RK-SWP{tag}{i:02d}", user_id=user.id, total_amount=15_000,
            shipping_fee=5_000, discount_amount=0, shipping_method=ShipmentMethod.PARCEL,
            status=OrderStatus.PENDING, recipient_name="스위퍼", recipient_phone="01000000000",
            zipcode="00000", address1="테스트 주소",
        )
        order.items = [
            OrderItem(product_id=product.id, product_title_snapshot="스위퍼", price_snapshot=10_000,
                      quantity=1)
        ]
        session.add(order)
        await session.flush()
        await session.execute(
            update(Order).where(Order.id == order.id).values(created_at=_NOW - age)
        )
        if with_ready:
            session.add(Payment(order_id=order.id, pg_provider=PgProvider.TOSS,
                                method=PaymentMethod.CARD, amount=15_000,
                                status=PaymentStatus.READY))
        numbers.append(order.order_number)
    await session.commit()
    return product.id, numbers


async def _cleanup(product_id: int, numbers: list[str]) -> None:
    async with async_session_factory() as cleanup:
        ids = select(Order.id).where(Order.order_number.in_(numbers))
        await cleanup.execute(delete(Payment).where(Payment.order_id.in_(ids)))
        await cleanup.execute(delete(Order).where(Order.order_number.in_(numbers)))
        await cleanup.execute(delete(Product).where(Product.id == product_id))
        await cleanup.commit()


async def _state(product_id: int, numbers: list[str]) -> tuple[int, list[OrderStatus]]:
    async with async_session_factory() as s:
        stock_stmt = select(Product.stock).where(Product.id == product_id)
        stock = (await s.execute(stock_stmt)).scalar_one()
        stmt = select(Order.order_number, Order.status).where(
            Order.order_number.in_(numbers)
        )
        rows = {number: status for number, status in (await s.execute(stmt)).all()}
    return stock, [rows[n] for n in numbers]


@pytest.mark.asyncio
async def test_sweep_releases_only_stale_and_safe_orders(db_session: AsyncSession) -> None:
    """30분 지난 주문만 정리, 토스 조회 실패 주문은 보류 — 보류 건이 있어도 스윕이 끝난다.

    Given: [31분·결제없음, 10분·결제없음, 31분·READY+조회실패, 40분·READY+토스404]
    Then:  0·3번만 CANCELLED, 재고 2 복구, 1·2번은 PENDING
    """
    product_id, numbers = await _seed(db_session, tag="A", specs=[
        (timedelta(minutes=31), False),
        (timedelta(minutes=10), False),
        (timedelta(minutes=31), True),
        (timedelta(minutes=40), True),
    ])
    gateway = _Gateway(unknown={numbers[2]})
    try:
        released = await asyncio.wait_for(
            sweep_abandoned_orders(
                async_session_factory, gateway, _NoopEmailSender(),  # type: ignore[arg-type]
                now=_NOW,
            ),
            timeout=10,
        )

        stock, statuses = await _state(product_id, numbers)
        assert released == 2
        assert statuses == [
            OrderStatus.CANCELLED, OrderStatus.PENDING, OrderStatus.PENDING, OrderStatus.CANCELLED,
        ]
        assert stock == 2
        assert gateway.lookups.count(numbers[2]) == 1, "보류 건은 같은 스윕에서 다시 조회하지 않음"
    finally:
        await _cleanup(product_id, numbers)


@pytest.mark.asyncio
async def test_sweep_concurrent_workers_restore_stock_once(db_session: AsyncSession) -> None:
    """gunicorn 워커 여러 개가 동시에 스윕해도 주문마다 재고는 한 번만 복구된다."""
    stale = timedelta(minutes=31)
    product_id, numbers = await _seed(db_session, tag="B", specs=[(stale, False)] * 5)
    try:
        results = await asyncio.gather(*[
            sweep_abandoned_orders(
                async_session_factory, _Gateway(), _NoopEmailSender(),  # type: ignore[arg-type]
                now=_NOW,
            )
            for _ in range(3)
        ])

        stock, statuses = await _state(product_id, numbers)
        assert sum(results) == 5
        assert stock == 5
        assert set(statuses) == {OrderStatus.CANCELLED}
    finally:
        await _cleanup(product_id, numbers)
