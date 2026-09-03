"""payment service 단위 테스트.

DB/PG 없이 FakeRepo + FakeGateway 로 결제 도메인 로직 검증.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import BackgroundTasks

from app.common.email import EmailSender
from app.core.exceptions import OrderNotFoundError, PaymentFailedError, PaymentGatewayUnknownError
from app.order.models import Order, OrderItem, OrderStatus
from app.payment.adapters.ports import (
    PaymentGateway,
    TossCancelResult,
    TossConfirmResult,
    TossPaymentResult,
)
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
    def __init__(
        self,
        *,
        should_fail: bool = False,
        should_timeout: bool = False,
        payment_status: str = "DONE",
        payment_total_amount: int = 300_000,
        get_payment_raises: bool = False,
        cancel_raises: Exception | None = None,
    ) -> None:
        self.should_fail = should_fail
        self.should_timeout = should_timeout
        # get_payment(웹훅 재조회)이 반환할 토스 결제 상태
        self.payment_status = payment_status
        # get_payment 이 반환할 토스 결제 금액 (로컬 Payment.amount 와 대조됨)
        self.payment_total_amount = payment_total_amount
        self.get_payment_raises = get_payment_raises
        self.cancel_raises = cancel_raises
        self.confirm_call_count: int = 0
        self.get_payment_call_count: int = 0
        self.cancel_calls: list[dict[str, object]] = []

    async def confirm(
        self, *, payment_key: str, order_id: str, amount: int
    ) -> TossConfirmResult:
        self.confirm_call_count += 1
        if self.should_timeout:
            raise PaymentGatewayUnknownError()
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

    async def get_payment(self, *, payment_key: str) -> TossPaymentResult:
        self.get_payment_call_count += 1
        if self.get_payment_raises:
            raise PaymentGatewayUnknownError()
        return TossPaymentResult(
            status=self.payment_status,
            method="카드",
            pg_tid=payment_key,
            total_amount=self.payment_total_amount,
            balance_amount=0,
            approved_at=datetime.now(UTC),
            card_company="신한카드",
            card_last4="1234",
            installment_months=0,
            approval_number="12345678",
        )

    async def cancel(
        self, *, payment_key: str, reason: str, cancel_amount: int | None = None
    ) -> TossCancelResult:
        self.cancel_calls.append(
            {"payment_key": payment_key, "reason": reason, "cancel_amount": cancel_amount}
        )
        if self.cancel_raises is not None:
            raise self.cancel_raises
        partial = cancel_amount is not None
        return TossCancelResult(
            status="PARTIAL_CANCELED" if partial else "CANCELED",
            cancelled_amount=cancel_amount or 300_000,
            balance_amount=100_000 if partial else 0,
            transaction_key="txn_fake",
        )


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
        # 락 버전 호출 추적 (Task 3-1 spy)
        self.locked_pg_tid_calls: int = 0
        self.unlocked_pg_tid_calls: int = 0
        self.locked_fallback_calls: int = 0
        self.locked_order_by_id_calls: int = 0

    async def get_by_id(self, payment_id: int) -> Payment | None:
        return next((p for p in self._payments if p.id == payment_id), None)

    async def get_by_order_id(self, order_id: int) -> list[Payment]:
        return [p for p in self._payments if p.order_id == order_id]

    async def get_by_order_id_with_lock(self, order_id: int) -> list[Payment]:
        # 단위 테스트에서는 락 없이 동일하게 동작
        return [p for p in self._payments if p.order_id == order_id]

    async def get_by_pg_tid(self, pg_tid: str) -> Payment | None:
        self.unlocked_pg_tid_calls += 1
        return next((p for p in self._payments if p.pg_tid == pg_tid), None)

    async def get_by_pg_tid_with_lock(self, pg_tid: str) -> Payment | None:
        self.locked_pg_tid_calls += 1
        return next((p for p in self._payments if p.pg_tid == pg_tid), None)

    async def get_order_by_number(self, order_number: str) -> Order | None:
        return next((o for o in self._orders if o.order_number == order_number), None)

    async def get_order_by_number_with_lock(self, order_number: str) -> Order | None:
        # 단위 테스트에서는 락 없이 동일하게 동작 (락은 실제 DB에서만 의미있음)
        return next((o for o in self._orders if o.order_number == order_number), None)

    async def get_order_by_id(self, order_id: int) -> Order | None:
        return next((o for o in self._orders if o.id == order_id), None)

    async def get_order_by_id_with_lock(self, order_id: int) -> Order | None:
        self.locked_order_by_id_calls += 1
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

    async def get_ready_payment_by_order_number_with_lock(
        self, order_number: str
    ) -> Payment | None:
        self.locked_fallback_calls += 1
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

    async def update_status_cancelled(
        self, payment: Payment, result: TossCancelResult
    ) -> None:
        partial = result.status == "PARTIAL_CANCELED" or result.balance_amount > 0
        payment.status = (
            PaymentStatus.PARTIAL_CANCELLED if partial else PaymentStatus.CANCELLED
        )
        payment.cancelled_at = datetime.now(UTC)

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


async def test_confirm_payment_gateway_timeout_raises_unknown_error_not_failed() -> None:
    """PG 네트워크 타임아웃 시 PaymentGatewayUnknownError가 발생한다 (PaymentFailedError 아님)."""
    order = make_order()
    payment = make_payment(order_id=1)
    service = _make_service(
        orders=[order], payments=[payment], gateway=_FakeGateway(should_timeout=True)
    )

    with pytest.raises(PaymentGatewayUnknownError):
        await service.confirm_payment(
            PaymentConfirmRequest(
                payment_key="k", order_id="RK-2606200001", amount=300_000
            ),
            BackgroundTasks(),
        )


async def test_confirm_payment_gateway_timeout_does_not_change_order_status() -> None:
    """PG 타임아웃 후에도 order.status는 PENDING 그대로 유지된다 (재시도 가능 상태)."""
    order = make_order()
    payment = make_payment(order_id=1)
    service = _make_service(
        orders=[order], payments=[payment], gateway=_FakeGateway(should_timeout=True)
    )

    with pytest.raises(PaymentGatewayUnknownError):
        await service.confirm_payment(
            PaymentConfirmRequest(
                payment_key="k", order_id="RK-2606200001", amount=300_000
            ),
            BackgroundTasks(),
        )

    assert order.status == OrderStatus.PENDING


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
    gw = _FakeGateway(payment_status="ABORTED")
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

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
    gw = _FakeGateway(payment_status="CANCELED")
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

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
    gw = _FakeGateway(payment_status="PARTIAL_CANCELED")
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_3", "status": "PARTIAL_CANCELED"},
        )
    )

    assert payment.status == PaymentStatus.PARTIAL_CANCELLED
    assert order.status == OrderStatus.PENDING
    assert repo.increment_calls == []


async def test_webhook_aborted_already_cancelled_order_does_not_double_restore() -> None:
    """주문이 이미 취소된 상태에서 ABORTED 웹훅이 재수신돼도 재고를 중복 복구하지 않는다."""
    order = _order_with_item(order_id=1, status=OrderStatus.CANCELLED)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid="pk_4")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    gw = _FakeGateway(payment_status="ABORTED")
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

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


# ── Task 3-1: handle_webhook 락 버전 조회 사용 확인 ──────────────


async def test_handle_webhook_uses_locked_payment_read() -> None:
    """handle_webhook 는 get_by_pg_tid_with_lock 을 사용하고, 락 없는 버전을 쓰지 않는다."""
    # Arrange
    order = make_order(order_id=1, status=OrderStatus.PENDING)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid="pk_lock_test")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]

    # Act
    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_lock_test", "status": "DONE"},
        )
    )

    # Assert: 락 버전만 호출, 락 없는 버전은 호출 안 됨
    assert repo.locked_pg_tid_calls == 1
    assert repo.unlocked_pg_tid_calls == 0


async def test_handle_webhook_fallback_uses_locked_read() -> None:
    """pg_tid fallback 경로도 get_ready_payment_by_order_number_with_lock 을 사용한다."""
    # Arrange: pg_tid 없는 READY 결제 (confirm 전 상태)
    order = make_order(order_id=1, order_number="RK-LOCK1", status=OrderStatus.PENDING)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid=None)
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]

    # Act: pg_tid 로 찾지 못하면 order_number fallback
    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_new", "orderId": "RK-LOCK1", "status": "DONE"},
        )
    )

    # Assert: 락 fallback 사용, 락 없는 fallback 은 사용 안 됨
    assert repo.locked_fallback_calls == 1
    assert repo.fallback_call_count == 0


async def test_restore_order_stock_uses_locked_order_read() -> None:
    """_restore_order_stock_and_cancel 는 get_order_by_id_with_lock 을 사용한다."""
    # Arrange: ABORTED 웹훅 → _restore_order_stock_and_cancel 호출
    order = _order_with_item(order_id=1, status=OrderStatus.PENDING)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid="pk_abort")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    gw = _FakeGateway(payment_status="ABORTED")
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    # Act
    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_abort", "status": "ABORTED"},
        )
    )

    # Assert: _restore_order_stock_and_cancel 에서 락 버전 사용
    assert repo.locked_order_by_id_calls >= 1


# ── Task 4: PAID 이후 환불/취소 웹훅 정상 처리 ─────────────────────────


async def test_webhook_canceled_after_paid_restores_stock_and_cancels_order() -> None:
    """PAID 결제에 CANCELED 웹훅 도착 → payment CANCELLED, order CANCELLED, 재고 복구."""
    # Arrange: 이미 결제 완료된 주문 (payment=PAID, order=PAID)
    order = _order_with_item(order_id=1, status=OrderStatus.PAID)
    payment = make_payment(order_id=1, status=PaymentStatus.PAID, pg_tid="pk_refund1")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    gw = _FakeGateway(payment_status="CANCELED")
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    # Act
    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_refund1", "status": "CANCELED"},
        )
    )

    # Assert
    assert payment.status == PaymentStatus.CANCELLED
    assert order.status == OrderStatus.CANCELLED
    assert repo.increment_calls == [(1, 2)]  # 재고 복구됨


async def test_webhook_partial_canceled_after_paid_does_not_restore_stock() -> None:
    """PAID 결제에 PARTIAL_CANCELED 웹훅 → payment PARTIAL_CANCELLED, 재고 복구는 안 됨."""
    # Arrange
    order = _order_with_item(order_id=1, status=OrderStatus.PAID)
    payment = make_payment(order_id=1, status=PaymentStatus.PAID, pg_tid="pk_partial1")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    gw = _FakeGateway(payment_status="PARTIAL_CANCELED")
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    # Act
    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_partial1", "status": "PARTIAL_CANCELED"},
        )
    )

    # Assert: payment만 PARTIAL_CANCELLED, order와 재고는 변화 없음 (기존 정책 유지)
    assert payment.status == PaymentStatus.PARTIAL_CANCELLED
    assert order.status == OrderStatus.PAID  # order는 그대로
    assert repo.increment_calls == []  # 재고 복구 안 됨


async def test_webhook_aborted_after_paid_is_ignored() -> None:
    """PAID 결제에 ABORTED 웹훅 도착 — PG에서 나올 수 없는 조합, 방어적으로 무시."""
    # Arrange
    order = _order_with_item(order_id=1, status=OrderStatus.PAID)
    payment = make_payment(order_id=1, status=PaymentStatus.PAID, pg_tid="pk_aborted_after_paid")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    gw = _FakeGateway(payment_status="ABORTED")
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    # Act
    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_aborted_after_paid", "status": "ABORTED"},
        )
    )

    # Assert: 아무것도 변하지 않아야 함
    assert payment.status == PaymentStatus.PAID
    assert order.status == OrderStatus.PAID
    assert repo.increment_calls == []


async def test_webhook_done_after_paid_is_still_idempotent_noop() -> None:
    """PAID 결제에 DONE 중복 웹훅 — 기존 멱등성 동작 회귀 보호."""
    # Arrange
    payment = make_payment(status=PaymentStatus.PAID, pg_tid="pk_done_dup")
    repo = _FakePaymentRepo(payments=[payment])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]

    original_status = payment.status

    # Act
    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_done_dup", "status": "DONE"},
        )
    )

    # Assert: 상태 변경 없음
    assert payment.status == original_status


# ── Task B: 웹훅 body 불신 + 조회 재확인 ──────────────────────────────


async def test_webhook_ignores_body_status_and_uses_gateway_refetch() -> None:
    """웹훅 body 의 status(DONE)를 무시하고, 조회 API 실제 상태(ABORTED)로 전이한다.

    토스 결제 웹훅에는 서명이 없으므로 body 를 신뢰하지 않는다.
    """
    order = _order_with_item(order_id=1, status=OrderStatus.PENDING)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid="pk_spoof")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    gw = _FakeGateway(payment_status="ABORTED")  # 실제 상태는 ABORTED
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_spoof", "status": "DONE"},  # body 는 DONE 이라 주장
        )
    )

    assert gw.get_payment_call_count == 1
    assert payment.status == PaymentStatus.FAILED
    assert order.status == OrderStatus.CANCELLED


async def test_webhook_expired_cancels_order_and_restores_stock() -> None:
    """결제 만료(EXPIRED) 웹훅 수신 시 주문이 취소되고 재고가 복구된다."""
    order = _order_with_item(order_id=1, status=OrderStatus.PENDING)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid="pk_exp")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    gw = _FakeGateway(payment_status="EXPIRED")
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_exp", "status": "EXPIRED"},
        )
    )

    assert payment.status == PaymentStatus.FAILED
    assert payment.fail_reason == "토스 결제 상태: EXPIRED"
    assert order.status == OrderStatus.CANCELLED
    assert repo.increment_calls == [(1, 2)]


async def test_webhook_in_progress_status_is_ignored() -> None:
    """승인 전 과도기 상태(IN_PROGRESS) 웹훅은 아무 전이도 하지 않는다."""
    order = make_order(order_id=1, status=OrderStatus.PENDING)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid="pk_prog")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    gw = _FakeGateway(payment_status="IN_PROGRESS")
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_prog", "status": "IN_PROGRESS"},
        )
    )

    assert payment.status == PaymentStatus.READY
    assert order.status == OrderStatus.PENDING


async def test_webhook_done_amount_mismatch_does_not_transition_to_paid() -> None:
    """웹훅 재조회 금액이 로컬 Payment.amount 와 다르면 PAID 로 전이하지 않는다.

    웹훅은 프론트 confirm 콜백이 유실됐을 때 결제를 확정하는 유일한 경로가 된다.
    confirm 이 금액을 검증하듯 웹훅 경로도 검증해야, 다른 결제거래의 paymentKey 로
    주문이 잘못 확정되는 걸 막는다.
    """
    order = make_order(order_id=1, status=OrderStatus.PENDING)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid="pk_amt")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    gw = _FakeGateway(payment_status="DONE", payment_total_amount=1_000)
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_amt", "status": "DONE"},
        )
    )

    assert payment.status == PaymentStatus.READY
    assert order.status == OrderStatus.PENDING
    assert order.paid_at is None


async def test_webhook_done_amount_match_transitions_to_paid() -> None:
    """웹훅 재조회 금액이 로컬 Payment.amount 와 일치하면 정상적으로 PAID 전이된다."""
    order = make_order(order_id=1, status=OrderStatus.PENDING)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid="pk_ok")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    gw = _FakeGateway(payment_status="DONE", payment_total_amount=payment.amount)
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED",
            data={"paymentKey": "pk_ok", "status": "DONE"},
        )
    )

    assert payment.status == PaymentStatus.PAID
    assert order.status == OrderStatus.PAID


async def test_webhook_propagates_gateway_unknown_error_when_refetch_fails() -> None:
    """조회 API 실패 시 PaymentGatewayUnknownError 를 전파한다 (라우터가 5xx → 토스 재시도)."""
    order = make_order(order_id=1, status=OrderStatus.PENDING)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid="pk_down")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    gw = _FakeGateway(get_payment_raises=True)
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    with pytest.raises(PaymentGatewayUnknownError):
        await service.handle_webhook(
            TossWebhookPayload(
                eventType="PAYMENT_STATUS_CHANGED",
                data={"paymentKey": "pk_down", "status": "DONE"},
            )
        )

    assert payment.status == PaymentStatus.READY  # 전이 안 됨


# ── cancel_payment (주문 취소/환불 시 order 모듈이 호출) ──────────────


async def test_cancel_payment_calls_gateway_and_marks_cancelled() -> None:
    """PAID 결제 전액 취소 → gateway.cancel 호출 + Payment CANCELLED."""
    paid = make_payment(order_id=1, status=PaymentStatus.PAID, pg_tid="pk_paid")
    repo = _FakePaymentRepo(payments=[paid])
    gw = _FakeGateway()
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    await service.cancel_payment(1, reason="구매자 취소")

    assert len(gw.cancel_calls) == 1
    assert gw.cancel_calls[0]["payment_key"] == "pk_paid"
    assert gw.cancel_calls[0]["cancel_amount"] is None
    assert paid.status == PaymentStatus.CANCELLED
    assert paid.cancelled_at is not None


async def test_cancel_payment_partial_marks_partial_cancelled() -> None:
    """부분 취소 금액을 넘기면 Payment PARTIAL_CANCELLED."""
    paid = make_payment(order_id=1, status=PaymentStatus.PAID, pg_tid="pk_paid")
    repo = _FakePaymentRepo(payments=[paid])
    gw = _FakeGateway()
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    await service.cancel_payment(1, reason="부분 환불", cancel_amount=100_000)

    assert gw.cancel_calls[0]["cancel_amount"] == 100_000
    assert paid.status == PaymentStatus.PARTIAL_CANCELLED


async def test_cancel_payment_no_paid_payment_is_noop() -> None:
    """PAID 결제가 없으면(결제 전 / 이미 취소) gateway 를 부르지 않고 조용히 끝낸다."""
    ready = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid=None)
    repo = _FakePaymentRepo(payments=[ready])
    gw = _FakeGateway()
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    await service.cancel_payment(1, reason="취소")

    assert gw.cancel_calls == []
    assert ready.status == PaymentStatus.READY


async def test_cancel_payment_missing_pg_tid_raises() -> None:
    """PAID 인데 pg_tid 가 없으면 취소 불가 — PaymentFailedError."""
    paid = make_payment(order_id=1, status=PaymentStatus.PAID, pg_tid=None)
    repo = _FakePaymentRepo(payments=[paid])
    gw = _FakeGateway()
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    with pytest.raises(PaymentFailedError):
        await service.cancel_payment(1, reason="취소")

    assert gw.cancel_calls == []


async def test_cancel_payment_propagates_gateway_rejection() -> None:
    """PG 가 취소를 거절하면 예외가 전파돼 상태 전환이 안 된다 (호출부 롤백)."""
    paid = make_payment(order_id=1, status=PaymentStatus.PAID, pg_tid="pk_paid")
    repo = _FakePaymentRepo(payments=[paid])
    gw = _FakeGateway(cancel_raises=PaymentFailedError("이미 취소된 결제"))
    service = PaymentService(repo, gw, _FakeEmailSender())  # type: ignore[arg-type]

    with pytest.raises(PaymentFailedError):
        await service.cancel_payment(1, reason="취소")

    assert paid.status == PaymentStatus.PAID  # 전환 안 됨
