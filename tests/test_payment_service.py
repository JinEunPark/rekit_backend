"""payment service 단위 테스트.

DB/PG 없이 FakeRepo + FakeGateway 로 결제 도메인 로직 검증.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.exceptions import OrderNotFound, PaymentFailed
from app.order.models import Order, OrderStatus
from app.payment.adapters.ports import PaymentGateway, TossConfirmResult
from app.payment.models import Payment, PaymentMethod, PaymentStatus, PgProvider
from app.payment.payment_schemas import (
    PaymentConfirmRequest,
    PaymentInitRequest,
    TossWebhookPayload,
)
from app.payment.payment_service import PaymentService


# ── 팩토리 ─────────────────────────────────────────────────────


def make_order(
    *,
    order_id: int = 1,
    user_id: int = 1,
    order_number: str = "RK-2606200001",
    total_amount: int = 300_000,
    status: OrderStatus = OrderStatus.PENDING,
) -> Order:
    from app.order.shipment import ShipmentMethod

    o = Order(
        order_number=order_number,
        user_id=user_id,
        total_amount=total_amount,
        shipping_fee=60_000,
        discount_amount=0,
        shipping_method=ShipmentMethod.FREIGHT,
        status=status,
        recipient_name="홍길동",
        recipient_phone="01012345678",
        zipcode="12345",
        address1="서울시 강남구",
    )
    o.id = order_id
    o.created_at = datetime.now(UTC)
    o.payments = []
    return o


def make_payment(
    *,
    payment_id: int = 1,
    order_id: int = 1,
    status: PaymentStatus = PaymentStatus.READY,
    pg_tid: str | None = None,
) -> Payment:
    p = Payment(
        order_id=order_id,
        pg_provider=PgProvider.TOSS,
        method=PaymentMethod.CARD,
        amount=300_000,
        status=status,
        pg_tid=pg_tid,
    )
    p.id = payment_id
    p.created_at = datetime.now(UTC)
    return p


# ── Fake Gateway ───────────────────────────────────────────────


class _FakeGateway:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail

    async def confirm(
        self, *, payment_key: str, order_id: str, amount: int
    ) -> TossConfirmResult:
        if self.should_fail:
            raise PaymentFailed("PG 확인 실패")
        return TossConfirmResult(
            method="카드",
            pg_tid=payment_key,
            paid_at=datetime.now(UTC),
            card_company="신한카드",
            card_last4="1234",
            installment_months=0,
            approval_number="12345678",
        )

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        return True


# ── Fake Repo ──────────────────────────────────────────────────


class _FakePaymentRepo:
    def __init__(
        self,
        orders: list[Order] | None = None,
        payments: list[Payment] | None = None,
    ) -> None:
        self._orders: list[Order] = list(orders or [])
        self._payments: list[Payment] = list(payments or [])
        self._next_id = 1

    async def get_by_id(self, payment_id: int) -> Payment | None:
        return next((p for p in self._payments if p.id == payment_id), None)

    async def get_by_order_id(self, order_id: int) -> list[Payment]:
        return [p for p in self._payments if p.order_id == order_id]

    async def get_by_pg_tid(self, pg_tid: str) -> Payment | None:
        return next((p for p in self._payments if p.pg_tid == pg_tid), None)

    async def get_order_by_number(self, order_number: str) -> Order | None:
        return next((o for o in self._orders if o.order_number == order_number), None)

    async def save(self, payment: Payment) -> Payment:
        payment.id = self._next_id
        self._next_id += 1
        self._payments.append(payment)
        return payment

    async def update_status_paid(
        self, payment: Payment, result: TossConfirmResult
    ) -> None:
        payment.status = PaymentStatus.PAID
        payment.pg_tid = result.pg_tid
        payment.paid_at = result.paid_at
        payment.card_company = result.card_company
        payment.card_last4 = result.card_last4
        payment.installment_months = result.installment_months
        payment.approval_number = result.approval_number

    async def update_order_paid(self, order: Order) -> None:
        order.status = OrderStatus.PAID
        order.paid_at = datetime.now(UTC)


def _make_service(
    orders: list[Order] | None = None,
    payments: list[Payment] | None = None,
    gateway: PaymentGateway | None = None,
) -> PaymentService:
    repo = _FakePaymentRepo(orders, payments)
    gw = gateway or _FakeGateway()
    return PaymentService(repo, gw)  # type: ignore[arg-type]


# ── init_payment ────────────────────────────────────────────────


async def test_init_payment_success() -> None:
    order = make_order()
    service = _make_service(orders=[order])

    result = await service.init_payment(
        user_id=1,
        req=PaymentInitRequest(order_number="RK-2606200001", method=PaymentMethod.CARD),
    )

    assert result.payment_id is not None
    assert result.order_number == "RK-2606200001"
    assert result.amount == 300_000


async def test_init_payment_order_not_found() -> None:
    service = _make_service()

    with pytest.raises(OrderNotFound):
        await service.init_payment(
            user_id=1,
            req=PaymentInitRequest(order_number="RK-NONE", method=PaymentMethod.CARD),
        )


async def test_init_payment_wrong_user_raises() -> None:
    order = make_order(user_id=1)
    service = _make_service(orders=[order])

    with pytest.raises(OrderNotFound):
        await service.init_payment(
            user_id=99,
            req=PaymentInitRequest(order_number="RK-2606200001", method=PaymentMethod.CARD),
        )


async def test_init_payment_already_paid_raises() -> None:
    order = make_order(status=OrderStatus.PAID)
    service = _make_service(orders=[order])

    with pytest.raises(PaymentFailed):
        await service.init_payment(
            user_id=1,
            req=PaymentInitRequest(order_number="RK-2606200001", method=PaymentMethod.CARD),
        )


# ── confirm_payment ─────────────────────────────────────────────


async def test_confirm_payment_success() -> None:
    order = make_order()
    payment = make_payment(order_id=1)
    service = _make_service(orders=[order], payments=[payment])

    result = await service.confirm_payment(
        PaymentConfirmRequest(
            payment_key="toss_key_abc",
            order_id="RK-2606200001",
            amount=300_000,
        )
    )

    assert result.order_number == "RK-2606200001"
    assert result.card_company == "신한카드"
    assert result.card_last4 == "1234"


async def test_confirm_payment_amount_mismatch_raises() -> None:
    order = make_order(total_amount=300_000)
    payment = make_payment(order_id=1)
    service = _make_service(orders=[order], payments=[payment])

    with pytest.raises(PaymentFailed):
        await service.confirm_payment(
            PaymentConfirmRequest(
                payment_key="k", order_id="RK-2606200001", amount=999_999
            )
        )


async def test_confirm_payment_gateway_fails() -> None:
    order = make_order()
    payment = make_payment(order_id=1)
    service = _make_service(
        orders=[order], payments=[payment], gateway=_FakeGateway(should_fail=True)
    )

    with pytest.raises(PaymentFailed):
        await service.confirm_payment(
            PaymentConfirmRequest(
                payment_key="k", order_id="RK-2606200001", amount=300_000
            )
        )


# ── handle_webhook ──────────────────────────────────────────────


async def test_webhook_idempotent_already_paid() -> None:
    """이미 PAID 인 pg_tid 로 웹훅 재수신 → 상태 변경 없이 정상 처리."""
    payment = make_payment(status=PaymentStatus.PAID, pg_tid="toss_key_xyz")
    service = _make_service(payments=[payment])

    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "toss_key_xyz", "status": "DONE"},
        )
    )

    assert payment.status == PaymentStatus.PAID


async def test_webhook_unknown_event_ignored() -> None:
    service = _make_service()
    await service.handle_webhook(
        TossWebhookPayload(eventType="UNKNOWN_EVENT", data={})
    )
