"""payment 모듈 Service — 결제 비즈니스 로직."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import BackgroundTasks

from app.common.email import EmailSender
from app.core.exceptions import OrderNotFoundError, PaymentFailedError
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

_EVENT_PAYMENT_STATUS_CHANGED = "PAYMENT_STATUS_CHANGED"
_TOSS_DONE = "DONE"
_TOSS_CANCELED = "CANCELED"
_TOSS_PARTIAL_CANCELED = "PARTIAL_CANCELED"
_TOSS_ABORTED = "ABORTED"


class PaymentService:
    """결제 플로우 오케스트레이터.

    init_payment  → 결제창 열기 전 Payment(READY) 생성
    confirm_payment → 프론트 성공 콜백 후 PG confirm + PAID 전환
    handle_webhook  → PG 웹훅 멱등 처리
    """

    def __init__(
        self,
        repo: PaymentRepository,
        gateway: PaymentGateway,
        email_sender: EmailSender,
    ) -> None:
        self._repo = repo
        self._gateway = gateway
        self._email_sender = email_sender

    async def init_payment(
        self, user_id: int, req: PaymentInitRequest
    ) -> PaymentInitResponse:
        """결제창 열기 전 초기화.

        1. order_number 로 주문 조회 + 소유권 확인
        2. PENDING 상태 확인 (이미 PAID/CANCELLED 이면 PaymentFailedError)
        3. Payment(status=READY) 생성 + save
        4. PaymentInitResponse 반환
        """
        # FOR UPDATE 락 — READY 확인 → 없으면 생성 구간을 원자적으로 처리 (Task 5-1 보강).
        order = await self._repo.get_order_by_number_with_lock(req.order_number)
        if order is None or order.user_id != user_id:
            raise OrderNotFoundError()

        if order.status != OrderStatus.PENDING:
            raise PaymentFailedError(f"주문 상태가 PENDING 이 아닙니다: {order.status}")

        existing_payments = await self._repo.get_by_order_id(order.id)
        payment = next(
            (p for p in existing_payments if p.status == PaymentStatus.READY), None
        )
        if payment is None:
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
        self,
        req: PaymentConfirmRequest,
        background_tasks: BackgroundTasks,
    ) -> PaymentConfirmResponse:
        """프론트 토스 성공 콜백 후 서버↔PG 최종 검증.

        1. order_number(=req.order_id) 로 주문 조회
        2. READY 상태 Payment 조회 (없으면 PaymentFailedError)
        3. amount == order.total_amount 검증
        4. gateway.confirm 호출
        5. payment PAID 전환 + order PAID 전환
        6. 결제 완료 이메일 발송 (BackgroundTasks)
        """
        order = await self._repo.get_order_by_number(req.order_id)
        if order is None:
            raise OrderNotFoundError()

        # READY 상태 결제 찾기
        payments = await self._repo.get_by_order_id(order.id)
        ready_payment = next(
            (p for p in payments if p.status == PaymentStatus.READY), None
        )
        if ready_payment is None:
            raise PaymentFailedError("결제 준비 중인 결제 건이 없습니다.")

        if req.amount != order.total_amount:
            raise PaymentFailedError(
                f"결제 금액 불일치: 요청 {req.amount}원 ≠ 주문 {order.total_amount}원"
            )

        result: TossConfirmResult = await self._gateway.confirm(
            payment_key=req.payment_key,
            order_id=req.order_id,
            amount=req.amount,
        )

        await self._repo.update_status_paid(ready_payment, result)
        await self._repo.update_order_paid(order)

        user_email = await self._repo.get_user_email(order.user_id)
        if user_email:
            background_tasks.add_task(
                _send_payment_confirmation_email,
                email_sender=self._email_sender,
                to=user_email,
                order_number=order.order_number,
                amount=order.total_amount,
                card_company=result.card_company,
                card_last4=result.card_last4,
                installment_months=result.installment_months,
            )

        return PaymentConfirmResponse(
            order_number=order.order_number,
            status=ready_payment.status,
            paid_at=ready_payment.paid_at,
            card_company=ready_payment.card_company,
            card_last4=ready_payment.card_last4,
            installment_months=ready_payment.installment_months,
        )

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        """웹훅 HMAC 서명 검증. router 가 _gateway 에 직접 접근하지 않도록 위임."""
        return self._gateway.verify_webhook_signature(body, signature)

    async def handle_webhook(self, payload: TossWebhookPayload) -> None:
        """PG 웹훅 처리. 멱등성 보장 — 이미 PAID 면 skip.

        eventType "PAYMENT_STATUS_CHANGED" 만 처리.
        data.status 에 따라 PAID/CANCELLED/FAILED 전환.
        """
        if payload.event_type != _EVENT_PAYMENT_STATUS_CHANGED:
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
        if pg_status == _TOSS_DONE:
            payment.status = PaymentStatus.PAID
        elif pg_status in (_TOSS_CANCELED, _TOSS_PARTIAL_CANCELED):
            payment.status = PaymentStatus.CANCELLED
            if pg_status == _TOSS_CANCELED:
                # 부분취소(PARTIAL_CANCELED)는 라인별 부분 환불 개념이 아직 모델에
                # 없어 전체 재고 복구 대상이 아님 — 현재는 의도적으로 스킵.
                # TODO: 부분 취소 시 라인별 재고 복구 정책 미정.
                await self._restore_order_stock_and_cancel(payment.order_id)
        elif pg_status == _TOSS_ABORTED:
            payment.status = PaymentStatus.FAILED
            payment.fail_reason = data.get("failure", {}).get("message")
            await self._restore_order_stock_and_cancel(payment.order_id)

    async def _restore_order_stock_and_cancel(self, order_id: int) -> None:
        """결제 실패/취소 웹훅 시 주문을 취소하고 재고를 복구한다. 중복 호출에 안전."""
        order = await self._repo.get_order_by_id(order_id)
        if order is None or order.status == OrderStatus.CANCELLED:
            return
        for item in order.items:
            await self._repo.increment_stock(item.product_id, item.quantity)
        order.status = OrderStatus.CANCELLED
        order.cancelled_at = datetime.now(UTC)


async def _send_payment_confirmation_email(
    *,
    email_sender: EmailSender,
    to: str,
    order_number: str,
    amount: int,
    card_company: str | None,
    card_last4: str | None,
    installment_months: int,
) -> None:
    """결제 완료 안내 메일 발송. BackgroundTasks 로 실행된다."""
    if card_company and card_last4:
        installment = "일시불" if installment_months == 0 else f"{installment_months}개월 할부"
        payment_info = f"{card_company} {card_last4} · {installment}"
    else:
        payment_info = "결제 완료"

    body = f"""안녕하세요, Rekle입니다.

결제가 완료되었습니다.

주문번호: {order_number}
결제금액: {amount:,}원
결제수단: {payment_info}

주문 내역은 마이페이지에서 확인하실 수 있습니다.

감사합니다.
Rekle 팀
"""
    await email_sender.send(
        to=to,
        subject=f"[Rekle] 주문 {order_number} 결제가 완료되었습니다",
        body=body,
    )
