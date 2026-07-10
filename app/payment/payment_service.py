"""payment 모듈 Service — 결제 비즈니스 로직."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

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

        # order.status가 PENDING인지 먼저 확인 — Task 2 타임아웃으로 취소된 주문 방어
        if order.status != OrderStatus.PENDING:
            raise PaymentFailedError(f"주문 상태가 PENDING 이 아닙니다: {order.status}")

        # FOR UPDATE 락으로 동시 confirm 이중 호출 방지 (Task 5-2)
        payments = await self._repo.get_by_order_id_with_lock(order.id)
        ready_payment = next(
            (p for p in payments if p.status == PaymentStatus.READY), None
        )
        already_paid = next(
            (p for p in payments if p.status == PaymentStatus.PAID), None
        )
        if ready_payment is None:
            if already_paid is not None:
                # 이미 확정된 결제 — 멱등 성공으로 처리, 게이트웨이 재호출 안 함
                return PaymentConfirmResponse(
                    order_number=order.order_number,
                    status=already_paid.status,
                    paid_at=already_paid.paid_at,
                    card_company=already_paid.card_company,
                    card_last4=already_paid.card_last4,
                    installment_months=already_paid.installment_months,
                )
            raise PaymentFailedError("결제 준비 중인 결제 건이 없습니다.")

        if req.amount != order.total_amount:
            raise PaymentFailedError(
                f"결제 금액 불일치: 요청 {req.amount}원 ≠ 주문 {order.total_amount}원"
            )

        result: TossConfirmResult = await self._gateway.confirm(
            payment_key=req.payment_key,
            order_id=req.order_id,
            amount=order.total_amount,  # req.amount 는 검증에만 사용, 실제 전달은 서버 신뢰값
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

        # FOR UPDATE 락 — 웹훅 재전송으로 동일 이벤트가 동시에 도착할 때 이중 처리 방지
        payment = await self._repo.get_by_pg_tid_with_lock(pg_tid)
        if payment is None:
            # confirm이 아직 실행 안 된 경우 pg_tid가 DB에 없을 수 있음 — orderId로 fallback
            order_number: str | None = data.get("orderId")
            if not order_number:
                return
            payment = await self._repo.get_ready_payment_by_order_number_with_lock(order_number)
            if payment is None:
                return

        pg_status: str = data.get("status", "")

        # PAID 상태에서 도착하는 웹훅은 pg_status별로 구분해 처리한다.
        # - DONE 재수신: 멱등 무시
        # - CANCELED/PARTIAL_CANCELED: 정상 환불 이벤트 — 아래 공통 로직으로 통과
        # - ABORTED: PG에서 나올 수 없는 조합, 방어적 무시
        if payment.status == PaymentStatus.PAID:
            if pg_status == _TOSS_DONE:
                return  # 중복 DONE 웹훅 — 기존 멱등성 동작 유지
            if pg_status in (_TOSS_CANCELED, _TOSS_PARTIAL_CANCELED):
                pass  # PAID 이후 정상 취소/환불 — 아래 공통 로직으로 흘려보냄
            else:
                # ABORTED 가 PAID 이후 도착 — PG 쪽에서 나올 수 없는 조합
                logger.warning("PAID 결제에 ABORTED 웹훅 도착 — 무시: pg_tid=%s", pg_tid)
                return

        if pg_status == _TOSS_DONE:
            payment.status = PaymentStatus.PAID
            payment.pg_tid = payment.pg_tid or pg_tid  # fallback 경로일 때만 채움
            order = await self._repo.get_order_by_id(payment.order_id)
            if order is not None and order.status == OrderStatus.PENDING:
                await self._repo.update_order_paid(order)
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
        """결제 실패/취소 웹훅 시 주문을 취소하고 재고를 복구한다.

        FOR UPDATE 락으로 동시 웹훅 재전송에 의한 재고 이중 복구를 방지한다.
        """
        order = await self._repo.get_order_by_id_with_lock(order_id)
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
