"""payment 모듈 Service — 결제 비즈니스 로직."""

from __future__ import annotations

from app.core.exceptions import OrderNotFound, PaymentFailed
from app.order.models import OrderStatus
from app.payment.adapters.ports import PaymentGateway, TossConfirmResult
from app.payment.models import Payment, PaymentStatus, PgProvider
from app.payment.payment_repository import PaymentRepository
from app.payment.payment_schemas import (
    PaymentConfirmRequest,
    PaymentConfirmResponse,
    PaymentInitRequest,
    PaymentInitResponse,
    TossWebhookPayload,
)


class PaymentService:
    """결제 플로우 오케스트레이터.

    init_payment  → 결제창 열기 전 Payment(READY) 생성
    confirm_payment → 프론트 성공 콜백 후 PG confirm + PAID 전환
    handle_webhook  → PG 웹훅 멱등 처리
    """

    def __init__(self, repo: PaymentRepository, gateway: PaymentGateway) -> None:
        self._repo = repo
        self._gateway = gateway

    async def init_payment(
        self, user_id: int, req: PaymentInitRequest
    ) -> PaymentInitResponse:
        """결제창 열기 전 초기화.

        1. order_number 로 주문 조회 + 소유권 확인
        2. PENDING 상태 확인 (이미 PAID/CANCELLED 이면 PaymentFailed)
        3. Payment(status=READY) 생성 + save
        4. PaymentInitResponse 반환
        """
        order = await self._repo.get_order_by_number(req.order_number)
        if order is None or order.user_id != user_id:
            raise OrderNotFound()

        if order.status != OrderStatus.PENDING:
            raise PaymentFailed(f"주문 상태가 PENDING 이 아닙니다: {order.status}")

        payment = Payment(
            order_id=order.id,
            pg_provider=PgProvider.TOSS,
            method=req.method,
            amount=order.total_amount,
            status=PaymentStatus.READY,
        )
        payment = await self._repo.save(payment)

        # user.username 은 order 에 직접 없으므로 recipient_name(스냅샷)을 대신 활용.
        # 실제 결제창 표시 이름: 배송지 수령인 이름이 가장 가까운 값.
        customer_name = order.recipient_name

        return PaymentInitResponse(
            payment_id=payment.id,
            order_number=order.order_number,
            amount=order.total_amount,
            customer_name=customer_name,
        )

    async def confirm_payment(
        self, req: PaymentConfirmRequest
    ) -> PaymentConfirmResponse:
        """프론트 토스 성공 콜백 후 서버↔PG 최종 검증.

        1. order_number(=req.order_id) 로 주문 조회
        2. READY 상태 Payment 조회 (없으면 PaymentFailed)
        3. amount == order.total_amount 검증
        4. gateway.confirm 호출
        5. payment PAID 전환 + order PAID 전환
        """
        order = await self._repo.get_order_by_number(req.order_id)
        if order is None:
            raise OrderNotFound()

        # READY 상태 결제 찾기
        payments = await self._repo.get_by_order_id(order.id)
        ready_payment = next(
            (p for p in payments if p.status == PaymentStatus.READY), None
        )
        if ready_payment is None:
            raise PaymentFailed("결제 준비 중인 결제 건이 없습니다.")

        if req.amount != order.total_amount:
            raise PaymentFailed(
                f"결제 금액 불일치: 요청 {req.amount}원 ≠ 주문 {order.total_amount}원"
            )

        result: TossConfirmResult = await self._gateway.confirm(
            payment_key=req.payment_key,
            order_id=req.order_id,
            amount=req.amount,
        )

        await self._repo.update_status_paid(ready_payment, result)
        await self._repo.update_order_paid(order)

        return PaymentConfirmResponse(
            order_number=order.order_number,
            status=ready_payment.status,
            paid_at=ready_payment.paid_at,
            card_company=ready_payment.card_company,
            card_last4=ready_payment.card_last4,
            installment_months=ready_payment.installment_months,
        )

    async def handle_webhook(self, payload: TossWebhookPayload) -> None:
        """PG 웹훅 처리. 멱등성 보장 — 이미 PAID 면 skip.

        eventType "PAYMENT_STATUS_CHANGED" 만 처리.
        data.status 에 따라 PAID/CANCELLED/FAILED 전환.
        """
        if payload.eventType != "PAYMENT_STATUS_CHANGED":
            return

        data = payload.data
        pg_tid: str | None = data.get("paymentKey")
        if not pg_tid:
            return

        payment = await self._repo.get_by_pg_tid(pg_tid)
        if payment is None:
            return

        # 멱등성: 이미 PAID 이면 중복 처리 없음
        if payment.status == PaymentStatus.PAID:
            return

        pg_status: str = data.get("status", "")
        if pg_status == "DONE":
            payment.status = PaymentStatus.PAID
        elif pg_status in ("CANCELED", "PARTIAL_CANCELED"):
            payment.status = PaymentStatus.CANCELLED
        elif pg_status == "ABORTED":
            payment.status = PaymentStatus.FAILED
            payment.fail_reason = data.get("failure", {}).get("message")
