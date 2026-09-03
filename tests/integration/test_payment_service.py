"""PaymentService 통합 테스트 — 실제 Postgres 대상 동시성 검증.

웹훅 재전송(동일 이벤트 동시 도착) 시 재고가 이중 복구되지 않음을 확인한다.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import ConditionGrade, Product, ProductStatus
from app.core.database import async_session_factory
from app.order.models import Order, OrderItem, OrderStatus
from app.order.shipment import ShipmentMethod
from app.payment.adapters.ports import TossConfirmResult, TossPaymentResult
from app.payment.models import Payment, PaymentMethod, PaymentStatus, PgProvider
from app.payment.payment_repository import PaymentRepository
from app.payment.payment_schemas import PaymentConfirmRequest, TossWebhookPayload
from app.payment.payment_service import PaymentService
from app.user.models import User

# ── 픽스처 헬퍼 ─────────────────────────────────────────────────────────


async def _get_user(session: AsyncSession) -> User:
    user = (await session.execute(select(User).limit(1))).scalars().first()
    assert user is not None, "테스트 대상 DB에 최소 1명의 User 가 있어야 함"
    return user


async def _make_product(session: AsyncSession, *, stock: int) -> Product:
    product = Product(
        title="웹훅동시성 테스트 상품",
        category="ETC",
        condition_grade=ConditionGrade.B,
        price=10_000,
        stock=stock,
        status=ProductStatus.ACTIVE,
    )
    session.add(product)
    await session.flush()
    return product


async def _make_pending_order_with_payment(
    session: AsyncSession,
    *,
    order_number: str,
    user_id: int,
    product_id: int,
    quantity: int,
    pg_tid: str,
) -> tuple[Order, Payment]:
    """PENDING 주문 + READY 결제를 함께 생성한다."""
    order = Order(
        order_number=order_number,
        user_id=user_id,
        total_amount=10_000 * quantity,
        shipping_fee=5_000,
        discount_amount=0,
        shipping_method=ShipmentMethod.PARCEL,
        status=OrderStatus.PENDING,
        recipient_name="웹훅테스트",
        recipient_phone="01000000000",
        zipcode="00000",
        address1="테스트 주소",
    )
    order.items = [
        OrderItem(
            product_id=product_id,
            product_title_snapshot="웹훅동시성 테스트 상품",
            price_snapshot=10_000,
            quantity=quantity,
        )
    ]
    session.add(order)
    await session.flush()

    payment = Payment(
        order_id=order.id,
        pg_provider=PgProvider.TOSS,
        method=PaymentMethod.CARD,
        amount=10_000 * quantity,
        status=PaymentStatus.READY,
        pg_tid=pg_tid,
    )
    session.add(payment)
    await session.flush()

    return order, payment


class _NoopEmailSender:
    async def send(self, *, to: str, subject: str, body: str, **_: object) -> None:
        del to, subject, body


def _toss_payment_result(payment_key: str, status: str) -> TossPaymentResult:
    return TossPaymentResult(
        status=status,
        method="카드",
        pg_tid=payment_key,
        total_amount=0,
        balance_amount=0,
        approved_at=datetime.now(UTC),
        card_company="신한카드",
        card_last4="1234",
        installment_months=0,
        approval_number="00000000",
    )


class _NoopGateway:
    def __init__(self, *, payment_status: str = "DONE") -> None:
        self.payment_status = payment_status

    async def confirm(self, *, payment_key: str, order_id: str, amount: int) -> TossConfirmResult:
        del order_id, amount
        return TossConfirmResult(
            method="카드",
            pg_tid=payment_key,
            paid_at=datetime.now(UTC),
            card_company="신한카드",
            card_last4="1234",
            installment_months=0,
            approval_number="00000000",
        )

    async def get_payment(self, *, payment_key: str) -> TossPaymentResult:
        return _toss_payment_result(payment_key, self.payment_status)


class _CountingGateway:
    """gateway.confirm 호출 횟수를 기록하는 스텁 — Task 5-1 동시 confirm 검증용."""

    def __init__(self) -> None:
        self.confirm_calls: int = 0

    async def confirm(self, *, payment_key: str, order_id: str, amount: int) -> TossConfirmResult:
        self.confirm_calls += 1
        del order_id, amount
        return TossConfirmResult(
            method="카드",
            pg_tid=payment_key,
            paid_at=datetime.now(UTC),
            card_company="신한카드",
            card_last4="1234",
            installment_months=0,
            approval_number="00000000",
        )

    async def get_payment(self, *, payment_key: str) -> TossPaymentResult:
        return _toss_payment_result(payment_key, "DONE")


# ── 동시성 테스트 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_aborted_concurrent_delivery_restores_stock_once(
    db_session: AsyncSession,
) -> None:
    """웹훅 재전송 시나리오: 동일 ABORTED 웹훅이 동시에 두 번 도착해도 재고 1회만 복구.

    Given: READY 결제, PENDING 주문(items 포함), 재고 5
    When:  asyncio.gather 로 동일 payload(ABORTED)를 handle_webhook 에 거의 동시에 두 번 전달
    Then:  재고는 5+2=7 (이중 복구 시 5+2+2=9 가 됨)
           order.status == CANCELLED 는 한 번만 전이
    """
    # Arrange
    user = await _get_user(db_session)
    product = await _make_product(db_session, stock=5)
    order, _ = await _make_pending_order_with_payment(
        db_session,
        order_number="RK-WBHKTEST0001",
        user_id=user.id,
        product_id=product.id,
        quantity=2,
        pg_tid="toss_pk_wbhk_test_001",
    )
    product_id = product.id
    order_number = order.order_number
    await db_session.commit()  # 다른 세션에서 보이게 커밋

    payload = TossWebhookPayload(
        eventType="PAYMENT_STATUS_CHANGED",
        data={"paymentKey": "toss_pk_wbhk_test_001", "status": "ABORTED"},
    )

    try:

        async def _handle_webhook() -> None:
            async with async_session_factory() as session:
                repo = PaymentRepository(session)
                service = PaymentService(
                    repo,
                    _NoopGateway(payment_status="ABORTED"),  # type: ignore[arg-type]
                    _NoopEmailSender(),  # type: ignore[arg-type]
                )
                await service.handle_webhook(payload)
                await session.commit()

        await asyncio.gather(
            _handle_webhook(),
            _handle_webhook(),
            return_exceptions=True,
        )

        # 재고 확인: 5(초기) + 2(1회 복구) = 7, 이중 복구 시 9
        async with async_session_factory() as verify_session:
            refreshed_product = (
                await verify_session.execute(
                    select(Product).where(Product.id == product_id)
                )
            ).scalar_one()
            assert refreshed_product.stock == 7, (
                f"재고가 7이어야 하는데 {refreshed_product.stock} — 이중 복구 발생"
            )

            refreshed_order = (
                await verify_session.execute(
                    select(Order).where(Order.order_number == order_number)
                )
            ).scalar_one()
            assert refreshed_order.status == OrderStatus.CANCELLED

    finally:
        async with async_session_factory() as cleanup:
            orders_to_del = (
                await cleanup.execute(
                    select(Order).where(Order.order_number == order_number)
                )
            ).scalars().all()
            for o in orders_to_del:
                await cleanup.execute(delete(Payment).where(Payment.order_id == o.id))
                await cleanup.execute(delete(OrderItem).where(OrderItem.order_id == o.id))
            await cleanup.execute(
                delete(Order).where(Order.order_number == order_number)
            )
            await cleanup.execute(delete(Product).where(Product.id == product_id))
            await cleanup.commit()


@pytest.mark.asyncio
async def test_confirm_payment_concurrent_calls_only_one_gateway_call(
    db_session: AsyncSession,
) -> None:
    """동시 confirm 시나리오: 같은 주문에 confirm_payment를 동시에 두 번 호출해도
    gateway.confirm 은 정확히 1회만 호출된다.

    Given: PENDING 주문 + READY 결제(pg_tid=None)
    When:  asyncio.gather 로 confirm_payment 를 거의 동시에 두 번 호출
    Then:  gateway.confirm 호출 횟수 == 1
           두 번째 호출은 이미 PAID 결제를 찾아 멱등 응답 반환
    """
    # Arrange
    user = await _get_user(db_session)
    product = await _make_product(db_session, stock=5)
    order_number = "RK-CFMTEST0001"
    quantity = 2
    total_amount = 10_000 * quantity

    order = Order(
        order_number=order_number,
        user_id=user.id,
        total_amount=total_amount,
        shipping_fee=5_000,
        discount_amount=0,
        shipping_method=ShipmentMethod.PARCEL,
        status=OrderStatus.PENDING,
        recipient_name="confirm테스트",
        recipient_phone="01000000000",
        zipcode="00000",
        address1="테스트 주소",
    )
    order.items = [
        OrderItem(
            product_id=product.id,
            product_title_snapshot="confirm테스트 상품",
            price_snapshot=10_000,
            quantity=quantity,
        )
    ]
    db_session.add(order)
    await db_session.flush()

    payment = Payment(
        order_id=order.id,
        pg_provider=PgProvider.TOSS,
        method=PaymentMethod.CARD,
        amount=total_amount,
        status=PaymentStatus.READY,
        # pg_tid 없음 — init_payment 이후 실제 상태와 동일
    )
    db_session.add(payment)
    await db_session.flush()
    product_id = product.id
    await db_session.commit()

    # 두 세션이 공유하는 counting gateway — asyncio 단일 스레드이므로 thread-safe
    shared_gateway = _CountingGateway()

    req = PaymentConfirmRequest(
        payment_key="toss_pk_confirm_test",
        order_id=order_number,
        amount=total_amount,
    )

    try:

        async def _confirm() -> None:
            async with async_session_factory() as session:
                repo = PaymentRepository(session)
                service = PaymentService(
                    repo,
                    shared_gateway,  # type: ignore[arg-type]
                    _NoopEmailSender(),  # type: ignore[arg-type]
                )
                await service.confirm_payment(req, BackgroundTasks())
                await session.commit()

        await asyncio.gather(_confirm(), _confirm(), return_exceptions=True)

        assert shared_gateway.confirm_calls == 1, (
            f"gateway.confirm 은 정확히 1회만 호출돼야 하는데 {shared_gateway.confirm_calls}회"
        )

        # 주문이 PAID 상태로 전이됐는지도 확인
        async with async_session_factory() as verify_session:
            refreshed_order = (
                await verify_session.execute(
                    select(Order).where(Order.order_number == order_number)
                )
            ).scalar_one()
            assert refreshed_order.status == OrderStatus.PAID

    finally:
        async with async_session_factory() as cleanup:
            await cleanup.execute(
                delete(Payment).where(Payment.order_id == order.id)
            )
            await cleanup.execute(
                delete(OrderItem).where(OrderItem.order_id == order.id)
            )
            await cleanup.execute(
                delete(Order).where(Order.order_number == order_number)
            )
            await cleanup.execute(delete(Product).where(Product.id == product_id))
            await cleanup.commit()


@pytest.mark.asyncio
async def test_init_payment_concurrent_calls_creates_only_one_ready_payment(
    db_session: AsyncSession,
) -> None:
    """동시 init_payment 시나리오: 같은 주문에 init_payment를 동시에 두 번 호출해도
    READY Payment 가 정확히 1개만 생성된다.

    Given: PENDING 주문(기존 Payment 없음)
    When:  asyncio.gather 로 init_payment 를 거의 동시에 두 번 호출
    Then:  DB 에 READY Payment 가 1개만 존재 (get_order_by_number_with_lock 이 블로킹)
    """
    # Arrange
    user = await _get_user(db_session)
    order_number = "RK-INITTEST0001"
    total_amount = 20_000

    order = Order(
        order_number=order_number,
        user_id=user.id,
        total_amount=total_amount,
        shipping_fee=5_000,
        discount_amount=0,
        shipping_method=ShipmentMethod.PARCEL,
        status=OrderStatus.PENDING,
        recipient_name="init테스트",
        recipient_phone="01000000000",
        zipcode="00000",
        address1="테스트 주소",
    )
    db_session.add(order)
    await db_session.flush()
    order_id = order.id
    user_id = user.id
    await db_session.commit()

    from app.payment.payment_schemas import PaymentInitRequest

    req = PaymentInitRequest(order_number=order_number, method=PaymentMethod.CARD)

    try:

        async def _init() -> None:
            async with async_session_factory() as session:
                repo = PaymentRepository(session)
                service = PaymentService(
                    repo,
                    _NoopGateway(),  # type: ignore[arg-type]
                    _NoopEmailSender(),  # type: ignore[arg-type]
                )
                await service.init_payment(user_id=user_id, req=req)
                await session.commit()

        await asyncio.gather(_init(), _init(), return_exceptions=True)

        # DB에 READY Payment 가 정확히 1개인지 확인
        async with async_session_factory() as verify_session:
            payments = (
                await verify_session.execute(
                    select(Payment).where(
                        Payment.order_id == order_id,
                        Payment.status == PaymentStatus.READY,
                    )
                )
            ).scalars().all()
            assert len(payments) == 1, (
                f"READY Payment 가 1개여야 하는데 {len(payments)}개 — 중복 생성"
            )

    finally:
        async with async_session_factory() as cleanup:
            await cleanup.execute(delete(Payment).where(Payment.order_id == order_id))
            await cleanup.execute(delete(Order).where(Order.order_number == order_number))
            await cleanup.commit()


@pytest.mark.asyncio
async def test_webhook_fallback_and_confirm_race_does_not_double_process(
    db_session: AsyncSession,
) -> None:
    """웹훅 fallback과 confirm 동시 실행: Payment가 정확히 한 번만 PAID로 전이된다.

    confirm 이 아직 실행 안 된 READY 결제(pg_tid=None)에 대해 DONE 웹훅이 fallback
    경로로 도착하는 동시에 confirm_payment 도 호출되는 경쟁 상황을 검증한다.

    Given: READY 결제(pg_tid=None), PENDING 주문
    When:  asyncio.gather 로 confirm_payment 와 handle_webhook(DONE, fallback 경로)를 동시 실행
    Then:  gateway.confirm 은 최대 1회 (confirm 경로만 호출), Payment 는 PAID 1개만 존재
    """
    # Arrange
    user = await _get_user(db_session)
    order_number = "RK-RACETEST0001"
    total_amount = 20_000

    order = Order(
        order_number=order_number,
        user_id=user.id,
        total_amount=total_amount,
        shipping_fee=5_000,
        discount_amount=0,
        shipping_method=ShipmentMethod.PARCEL,
        status=OrderStatus.PENDING,
        recipient_name="race테스트",
        recipient_phone="01000000000",
        zipcode="00000",
        address1="테스트 주소",
    )
    db_session.add(order)
    await db_session.flush()
    order_id = order.id

    payment = Payment(
        order_id=order_id,
        pg_provider=PgProvider.TOSS,
        method=PaymentMethod.CARD,
        amount=total_amount,
        status=PaymentStatus.READY,
        # pg_tid=None — confirm 이전이므로 pg_tid 없음 (fallback 경로 트리거)
    )
    db_session.add(payment)
    await db_session.flush()
    await db_session.commit()

    shared_gateway = _CountingGateway()

    # DONE 웹훅 — pg_tid 없으므로 orderId(=order_number) fallback 경로로 조회
    webhook_payload = TossWebhookPayload(
        eventType="PAYMENT_STATUS_CHANGED",
        data={
            "paymentKey": "toss_pk_race_test",
            "orderId": order_number,
            "status": "DONE",
        },
    )
    confirm_req = PaymentConfirmRequest(
        payment_key="toss_pk_race_test",
        order_id=order_number,
        amount=total_amount,
    )

    try:

        async def _confirm() -> None:
            async with async_session_factory() as session:
                repo = PaymentRepository(session)
                service = PaymentService(
                    repo,
                    shared_gateway,  # type: ignore[arg-type]
                    _NoopEmailSender(),  # type: ignore[arg-type]
                )
                await service.confirm_payment(confirm_req, BackgroundTasks())
                await session.commit()

        async def _webhook() -> None:
            async with async_session_factory() as session:
                repo = PaymentRepository(session)
                service = PaymentService(
                    repo,
                    _NoopGateway(),  # type: ignore[arg-type]
                    _NoopEmailSender(),  # type: ignore[arg-type]
                )
                await service.handle_webhook(webhook_payload)
                await session.commit()

        await asyncio.gather(_confirm(), _webhook(), return_exceptions=True)

        # 최종 결제 상태 확인
        async with async_session_factory() as verify_session:
            payments = (
                await verify_session.execute(
                    select(Payment).where(Payment.order_id == order_id)
                )
            ).scalars().all()

            # PAID Payment 가 정확히 1개여야 함 (이중 처리 없음)
            paid_payments = [p for p in payments if p.status == PaymentStatus.PAID]
            assert len(paid_payments) == 1, (
                f"PAID Payment 가 1개여야 하는데 {len(paid_payments)}개"
            )

            # gateway.confirm 은 confirm_payment 경로에서만 호출 (웹훅 DONE은 gateway 호출 안 함)
            assert shared_gateway.confirm_calls <= 1, (
                f"gateway.confirm 이 중복 호출됨: {shared_gateway.confirm_calls}회"
            )

    finally:
        async with async_session_factory() as cleanup:
            await cleanup.execute(delete(Payment).where(Payment.order_id == order_id))
            await cleanup.execute(delete(OrderItem).where(OrderItem.order_id == order_id))
            await cleanup.execute(delete(Order).where(Order.order_number == order_number))
            await cleanup.commit()
