"""payment service 단위 테스트.

DB/PG 없이 FakeRepo + FakeGateway 로 결제 도메인 로직 검증.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import BackgroundTasks

from app.common.email import EmailSender
from app.core.exceptions import OrderNotFoundError, PaymentFailedError
from app.order.models import Order, OrderItem, OrderStatus
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
        self.confirm_call_count: int = 0

    async def confirm(
        self, *, payment_key: str, order_id: str, amount: int
    ) -> TossConfirmResult:
        self.confirm_call_count += 1
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
        self.increment_calls: list[tuple[int, int]] = []
        self.fallback_call_count: int = 0

    async def get_by_id(self, payment_id: int) -> Payment | None:
        return next((p for p in self._payments if p.id == payment_id), None)

    async def get_by_order_id(self, order_id: int) -> list[Payment]:
        return [p for p in self._payments if p.order_id == order_id]

    async def get_by_order_id_with_lock(self, order_id: int) -> list[Payment]:
        # 단위 테스트에서는 락 없이 동일하게 동작
        return [p for p in self._payments if p.order_id == order_id]

    async def get_by_pg_tid(self, pg_tid: str) -> Payment | None:
        return next((p for p in self._payments if p.pg_tid == pg_tid), None)

    async def get_order_by_number(self, order_number: str) -> Order | None:
        return next((o for o in self._orders if o.order_number == order_number), None)

    async def get_order_by_number_with_lock(self, order_number: str) -> Order | None:
        # 단위 테스트에서는 락 없이 동일하게 동작 (락은 실제 DB에서만 의미있음)
        return next((o for o in self._orders if o.order_number == order_number), None)

    async def get_order_by_id(self, order_id: int) -> Order | None:
        return next((o for o in self._orders if o.id == order_id), None)

    async def get_ready_payment_by_order_number(self, order_number: str) -> Payment | None:
        self.fallback_call_count += 1
        order = next((o for o in self._orders if o.order_number == order_number), None)
        if order is None:
            return None
        return next(
            (
                p
                for p in self._payments
                if p.order_id == order.id and p.status == PaymentStatus.READY
            ),
            None,
        )

    async def increment_stock(self, product_id: int, quantity: int) -> None:
        self.increment_calls.append((product_id, quantity))

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


async def test_init_payment_reuses_existing_ready_payment() -> None:
    """이미 READY 결제가 있으면 새로 생성하지 않고 그대로 재사용한다 (멱등성)."""
    order = make_order()
    existing = make_payment(payment_id=99, order_id=1, status=PaymentStatus.READY)
    repo = _FakePaymentRepo(orders=[order], payments=[existing])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]

    result = await service.init_payment(
        user_id=1,
        req=PaymentInitRequest(order_number="RK-2606200001", method=PaymentMethod.CARD),
    )

    assert result.payment_id == 99
    assert len(repo._payments) == 1


async def test_init_payment_ignores_non_ready_payments_when_checking_ready() -> None:
    """READY가 아닌(취소된) 과거 결제는 재사용 대상이 아니고 새로 생성된다."""
    order = make_order()
    cancelled = make_payment(payment_id=5, order_id=1, status=PaymentStatus.CANCELLED)
    repo = _FakePaymentRepo(orders=[order], payments=[cancelled])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]

    result = await service.init_payment(
        user_id=1,
        req=PaymentInitRequest(order_number="RK-2606200001", method=PaymentMethod.CARD),
    )

    assert result.payment_id != 5
    assert len(repo._payments) == 2


# ── confirm_payment ─────────────────────────────────────────────


async def test_confirm_payment_on_already_paid_order_is_idempotent_no_gateway_call() -> None:
    """READY 없고 PAID만 있으면 게이트웨이 호출 없이 기존 PAID 정보로 반환 (멱등성)."""
    order = make_order()
    paid_payment = make_payment(
        payment_id=42, order_id=1, status=PaymentStatus.PAID, pg_tid="toss_key_paid"
    )
    paid_payment.paid_at = datetime.now(UTC)
    paid_payment.card_company = "국민카드"
    paid_payment.card_last4 = "5678"
    paid_payment.installment_months = 0

    gw = _FakeGateway()
    repo = _FakePaymentRepo(orders=[order], payments=[paid_payment])
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    result = await service.confirm_payment(
        PaymentConfirmRequest(
            payment_key="toss_key_paid",
            order_id="RK-2606200001",
            amount=300_000,
        ),
        BackgroundTasks(),
    )

    assert result.order_number == "RK-2606200001"
    assert result.card_company == "국민카드"
    assert gw.confirm_call_count == 0  # 게이트웨이 호출 없음


async def test_confirm_payment_on_cancelled_order_raises() -> None:
    """order.status가 CANCELLED이면 PaymentFailedError 발생, 게이트웨이 호출 없음 (Task 5-3)."""
    order = make_order(status=OrderStatus.CANCELLED)
    payment = make_payment(order_id=1, status=PaymentStatus.READY)
    gw = _FakeGateway()
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    with pytest.raises(PaymentFailedError):
        await service.confirm_payment(
            PaymentConfirmRequest(
                payment_key="k", order_id="RK-2606200001", amount=300_000
            ),
            BackgroundTasks(),
        )

    assert gw.confirm_call_count == 0


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


# ── webhook: DONE 시 order.status PAID 전환 (Task 3-1) ─────────────────────


async def test_webhook_done_transitions_order_to_paid() -> None:
    """웹훅 DONE 수신 시 payment.status=PAID, order.status=PAID로 전환된다."""
    order = make_order(order_id=1, status=OrderStatus.PENDING)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid="pk_done")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]

    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_done", "status": "DONE"},
        )
    )

    assert payment.status == PaymentStatus.PAID
    assert order.status == OrderStatus.PAID
    assert order.paid_at is not None


async def test_webhook_done_on_already_paid_order_is_noop_for_order() -> None:
    """이미 PAID인 payment에 DONE 웹훅 재수신 → 멱등성 가드에서 걸려 order 변경 없음."""
    order = make_order(order_id=1, status=OrderStatus.PAID)
    payment = make_payment(order_id=1, status=PaymentStatus.PAID, pg_tid="pk_dup")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]

    original_status = order.status

    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_dup", "status": "DONE"},
        )
    )

    assert order.status == original_status  # 변경 없음


async def test_webhook_done_order_already_missing_is_noop() -> None:
    """payment.order_id가 가리키는 Order가 없어도 예외 없이 조용히 처리된다."""
    payment = make_payment(order_id=999, status=PaymentStatus.READY, pg_tid="pk_orphan")
    repo = _FakePaymentRepo(orders=[], payments=[payment])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]

    # 예외 없이 처리돼야 함
    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_orphan", "status": "DONE"},
        )
    )

    assert payment.status == PaymentStatus.PAID  # payment는 PAID 전환됨


# ── webhook: orderId fallback 조회 (Task 3-2) ─────────────────────


async def test_webhook_arrives_before_confirm_finds_payment_by_order_id_fallback() -> None:
    """pg_tid로 찾지 못하면 orderId(order_number)로 READY 결제를 fallback 조회한다."""
    order = make_order(order_id=1, order_number="RK-1", status=OrderStatus.PENDING)
    # confirm 전 상태: pg_tid가 없는 READY 결제
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid=None)
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]

    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_new", "orderId": "RK-1", "status": "DONE"},
        )
    )

    assert payment.status == PaymentStatus.PAID
    assert payment.pg_tid == "pk_new"
    assert order.status == OrderStatus.PAID


async def test_webhook_fallback_when_no_ready_payment_and_no_pg_tid_match_is_noop() -> None:
    """pg_tid로도, orderId fallback으로도 찾지 못하면 조용히 return."""
    repo = _FakePaymentRepo(orders=[], payments=[])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]

    # 예외 없이 조용히 처리돼야 함
    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_x", "orderId": "RK-NONE", "status": "DONE"},
        )
    )


async def test_webhook_pg_tid_found_directly_does_not_use_fallback() -> None:
    """pg_tid로 직접 찾으면 get_ready_payment_by_order_number가 호출되지 않는다."""
    order = make_order(order_id=1, order_number="RK-2606200001", status=OrderStatus.PENDING)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid="pk_direct")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]

    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_direct", "orderId": "RK-2606200001", "status": "DONE"},
        )
    )

    assert repo.fallback_call_count == 0


# ── webhook: 실패/취소 시 재고 복구 (Task 1-4) ─────────────────────


def _order_with_item(**kwargs) -> Order:
    order = make_order(**kwargs)
    order.items = [
        OrderItem(
            product_id=1,
            product_title_snapshot="상품",
            price_snapshot=100_000,
            quantity=2,
        )
    ]
    return order


async def test_webhook_aborted_cancels_order_and_restores_stock() -> None:
    """결제 거절(ABORTED) 웹훅 수신 시 주문이 취소되고 재고가 복구된다."""
    order = _order_with_item(order_id=1, status=OrderStatus.PENDING)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid="pk_1")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]

    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_1", "status": "ABORTED"},
        )
    )

    assert payment.status == PaymentStatus.FAILED
    assert order.status == OrderStatus.CANCELLED
    assert repo.increment_calls == [(1, 2)]


async def test_webhook_canceled_cancels_order_and_restores_stock() -> None:
    """결제 취소(CANCELED) 웹훅 수신 시 주문이 취소되고 재고가 복구된다."""
    order = _order_with_item(order_id=1, status=OrderStatus.PENDING)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid="pk_2")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]

    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_2", "status": "CANCELED"},
        )
    )

    assert payment.status == PaymentStatus.CANCELLED
    assert order.status == OrderStatus.CANCELLED
    assert repo.increment_calls == [(1, 2)]


async def test_webhook_partial_canceled_does_not_restore_stock() -> None:
    """부분취소(PARTIAL_CANCELED)는 order/재고에 영향을 주지 않는다 (정책 미정, 현재 동작 고정)."""
    order = _order_with_item(order_id=1, status=OrderStatus.PENDING)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid="pk_3")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]

    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_3", "status": "PARTIAL_CANCELED"},
        )
    )

    assert payment.status == PaymentStatus.CANCELLED
    assert order.status == OrderStatus.PENDING
    assert repo.increment_calls == []


async def test_webhook_aborted_already_cancelled_order_does_not_double_restore() -> None:
    """주문이 이미 취소된 상태에서 ABORTED 웹훅이 재수신돼도 재고를 중복 복구하지 않는다."""
    order = _order_with_item(order_id=1, status=OrderStatus.CANCELLED)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid="pk_4")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]

    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_4", "status": "ABORTED"},
        )
    )

    assert repo.increment_calls == []


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
