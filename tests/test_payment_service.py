"""payment service 단위 테스트.

DB/PG 없이 FakeRepo + FakeGateway 로 결제 도메인 로직 검증.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import BackgroundTasks

from app.common.email import EmailSender
from app.core.exceptions import OrderNotFoundError, PaymentFailedError
from app.order.models import Order, OrderStatus
from app.payment.adapters.ports import PaymentGateway, TossConfirmResult
from app.payment.models import Payment, PaymentMethod, PaymentStatus, PgProvider
from app.payment.payment_schemas import (
    PaymentConfirmRequest,
    PaymentInitRequest,
    TossWebhookPayload,
)
from app.payment.payment_service import PaymentService


class _FakeEmailSender:
    async def send(
        self, *, to: str, subject: str, body: str, html_body: str | None = None
    ) -> None:
        del to, subject, body, html_body


_: EmailSender = _FakeEmailSender()  # type: ignore[assignment]

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
            raise PaymentFailedError("PG 확인 실패")
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

    async def get_user_email(self, _: int) -> str | None:
        return "test@example.com"


def _make_service(
    orders: list[Order] | None = None,
    payments: list[Payment] | None = None,
    gateway: PaymentGateway | None = None,
) -> PaymentService:
    repo = _FakePaymentRepo(orders, payments)
    gw = gateway or _FakeGateway()
    return PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]


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

    with pytest.raises(OrderNotFoundError):
        await service.init_payment(
            user_id=1,
            req=PaymentInitRequest(order_number="RK-NONE", method=PaymentMethod.CARD),
        )


async def test_init_payment_wrong_user_raises() -> None:
    order = make_order(user_id=1)
    service = _make_service(orders=[order])

    with pytest.raises(OrderNotFoundError):
        await service.init_payment(
            user_id=99,
            req=PaymentInitRequest(order_number="RK-2606200001", method=PaymentMethod.CARD),
        )


async def test_init_payment_already_paid_raises() -> None:
    order = make_order(status=OrderStatus.PAID)
    service = _make_service(orders=[order])

    with pytest.raises(PaymentFailedError):
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
        ),
        BackgroundTasks(),
    )

    assert result.order_number == "RK-2606200001"
    assert result.card_company == "신한카드"
    assert result.card_last4 == "1234"


async def test_confirm_payment_amount_mismatch_raises() -> None:
    order = make_order(total_amount=300_000)
    payment = make_payment(order_id=1)
    service = _make_service(orders=[order], payments=[payment])

    with pytest.raises(PaymentFailedError):
        await service.confirm_payment(
            PaymentConfirmRequest(
                payment_key="k", order_id="RK-2606200001", amount=999_999
            ),
            BackgroundTasks(),
        )


async def test_confirm_payment_gateway_fails() -> None:
    order = make_order()
    payment = make_payment(order_id=1)
    service = _make_service(
        orders=[order], payments=[payment], gateway=_FakeGateway(should_fail=True)
    )

    with pytest.raises(PaymentFailedError):
        await service.confirm_payment(
            PaymentConfirmRequest(
                payment_key="k", order_id="RK-2606200001", amount=300_000
            ),
            BackgroundTasks(),
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


# ── confirm_payment: 이메일 발송 ────────────────────────────────


async def test_confirm_payment_registers_email_task() -> None:
    """결제 성공 시 BackgroundTasks 에 이메일 태스크가 1개 등록된다."""
    order = make_order()
    payment = make_payment(order_id=1)
    service = _make_service(orders=[order], payments=[payment])
    bg = BackgroundTasks()

    await service.confirm_payment(
        PaymentConfirmRequest(
            payment_key="toss_key_abc",
            order_id="RK-2606200001",
            amount=300_000,
        ),
        bg,
    )

    assert len(bg.tasks) == 1
    assert bg.tasks[0].kwargs["to"] == "test@example.com"
    assert "RK-2606200001" in str(bg.tasks[0].kwargs["order_number"])


async def test_confirm_payment_no_email_task_when_no_user_email() -> None:
    """유저 이메일이 없으면 이메일 태스크가 등록되지 않는다."""

    class _NoEmailRepo(_FakePaymentRepo):
        async def get_user_email(self, _: int) -> str | None:
            return None

    order = make_order()
    payment = make_payment(order_id=1)
    repo = _NoEmailRepo(orders=[order], payments=[payment])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]
    bg = BackgroundTasks()

    await service.confirm_payment(
        PaymentConfirmRequest(
            payment_key="k", order_id="RK-2606200001", amount=300_000
        ),
        bg,
    )

    assert bg.tasks == []


# ── _send_payment_confirmation_email: 이메일 본문 ───────────────


class _RecordingEmailSender:
    """발송된 메일을 records 에 누적한다."""

    def __init__(self) -> None:
        self.records: list[dict[str, str]] = []

    async def send(
        self, *, to: str, subject: str, body: str, html_body: str | None = None
    ) -> None:
        del html_body
        self.records.append({"to": to, "subject": subject, "body": body})


async def test_payment_email_subject_contains_order_number() -> None:
    """제목에 주문번호가 포함되어야 한다."""
    from app.payment.payment_service import _send_payment_confirmation_email

    sender = _RecordingEmailSender()
    await _send_payment_confirmation_email(
        email_sender=sender,  # type: ignore[arg-type]
        to="buyer@example.com",
        order_number="RK-2606200001",
        amount=300_000,
        card_company="신한카드",
        card_last4="1234",
        installment_months=0,
    )

    assert "RK-2606200001" in sender.records[0]["subject"]


async def test_payment_email_body_card_lump_sum() -> None:
    """카드 일시불 결제 시 본문에 카드사·끝번호·일시불이 포함된다."""
    from app.payment.payment_service import _send_payment_confirmation_email

    sender = _RecordingEmailSender()
    await _send_payment_confirmation_email(
        email_sender=sender,  # type: ignore[arg-type]
        to="buyer@example.com",
        order_number="RK-2606200001",
        amount=300_000,
        card_company="신한카드",
        card_last4="1234",
        installment_months=0,
    )

    body = sender.records[0]["body"]
    assert "신한카드" in body
    assert "1234" in body
    assert "일시불" in body
    assert "300,000" in body


async def test_payment_email_body_installment() -> None:
    """할부 결제 시 본문에 N개월 할부가 표시된다."""
    from app.payment.payment_service import _send_payment_confirmation_email

    sender = _RecordingEmailSender()
    await _send_payment_confirmation_email(
        email_sender=sender,  # type: ignore[arg-type]
        to="buyer@example.com",
        order_number="RK-2606200002",
        amount=500_000,
        card_company="현대카드",
        card_last4="5678",
        installment_months=3,
    )

    assert "3개월 할부" in sender.records[0]["body"]


async def test_payment_email_body_no_card_info() -> None:
    """카드 정보 없을 때(계좌이체 등) 본문에 '결제 완료'가 표시된다."""
    from app.payment.payment_service import _send_payment_confirmation_email

    sender = _RecordingEmailSender()
    await _send_payment_confirmation_email(
        email_sender=sender,  # type: ignore[arg-type]
        to="buyer@example.com",
        order_number="RK-2606200003",
        amount=150_000,
        card_company=None,
        card_last4=None,
        installment_months=0,
    )

    assert "결제 완료" in sender.records[0]["body"]
