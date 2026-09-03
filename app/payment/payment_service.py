"""payment 모듈 Service — 결제 비즈니스 로직."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import BackgroundTasks

from app.common.email import EmailSender
from app.core.exceptions import OrderNotFoundError, PaymentFailedError
from app.order.models import OrderStatus
from app.payment.adapters.ports import (
    PaymentGateway,
    TossConfirmResult,
    TossPaymentResult,
)
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
_TOSS_EXPIRED = "EXPIRED"
# 승인 전 과도기 상태 — 웹훅으로 도착해도 확정 전이므로 무시하고 다음 웹훅을 기다린다.
_TOSS_PENDING_STATUSES = frozenset({"READY", "IN_PROGRESS", "WAITING_FOR_DEPOSIT"})


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

    async def handle_webhook(self, payload: TossWebhookPayload) -> None:
        """PG 웹훅 처리.

        토스 결제 웹훅에는 서명이 없어서 body 를 신뢰할 수 없다. paymentKey 로
        결제 조회 API 를 호출해 **실제 상태**를 재확인하고, 그 결과로만 전이한다.
        멱등성 보장 — 이미 확정된 결제면 skip.

        조회 자체에 실패하면 PaymentGatewayUnknownError 가 전파돼 라우터가 5xx 를
        반환하고, 토스가 웹훅을 재시도한다.
        """
        if payload.event_type != _EVENT_PAYMENT_STATUS_CHANGED:
            return

        data = payload.data
        payment_key: str | None = data.get("paymentKey")
        if not payment_key:
            return

        # 웹훅 body 대신 조회 API 로 실제 상태를 가져온다.
        remote = await self._gateway.get_payment(payment_key=payment_key)

        # FOR UPDATE 락 — 웹훅 재전송으로 동일 이벤트가 동시에 도착할 때 이중 처리 방지
        payment = await self._repo.get_by_pg_tid_with_lock(payment_key)
        if payment is None:
            # confirm이 아직 실행 안 된 경우 pg_tid가 DB에 없을 수 있음 — orderId로 fallback
            order_number: str | None = data.get("orderId")
            if not order_number:
                return
            payment = await self._repo.get_ready_payment_by_order_number_with_lock(
                order_number
            )
            if payment is None:
                return

        await self._apply_remote_payment_status(payment, remote)

    async def _apply_remote_payment_status(
        self, payment: Payment, remote: TossPaymentResult
    ) -> None:
        """토스 결제 조회 결과(remote.status)로 로컬 payment/order 상태를 전이한다."""
        status = remote.status

        # 이미 확정된 결제 — DONE 재수신은 멱등 무시. 취소류(CANCELED/PARTIAL_CANCELED)만
        # 아래 공통 로직으로 흘려보낸다.
        if payment.status == PaymentStatus.PAID and status not in (
            _TOSS_CANCELED,
            _TOSS_PARTIAL_CANCELED,
        ):
            if status != _TOSS_DONE:
                logger.warning(
                    "PAID 결제에 예상 밖 상태 %s — 무시: pg_tid=%s",
                    status,
                    payment.pg_tid,
                )
            return

        if status == _TOSS_DONE:
            payment.status = PaymentStatus.PAID
            payment.pg_tid = payment.pg_tid or remote.pg_tid  # fallback 경로일 때만 채움
            # 웹훅이 confirm 보다 먼저 도착한 경우 영수증 메타데이터도 여기서 채운다.
            if payment.paid_at is None:
                payment.paid_at = remote.approved_at
                payment.card_company = remote.card_company
                payment.card_last4 = remote.card_last4
                payment.installment_months = remote.installment_months
                payment.approval_number = remote.approval_number
            order = await self._repo.get_order_by_id(payment.order_id)
            if order is not None and order.status == OrderStatus.PENDING:
                await self._repo.update_order_paid(order)
        elif status == _TOSS_CANCELED:
            payment.status = PaymentStatus.CANCELLED
            await self._restore_order_stock_and_cancel(payment.order_id)
        elif status == _TOSS_PARTIAL_CANCELED:
            # 부분 취소는 라인별 부분 환불 개념이 아직 모델에 없어 재고 복구 대상이 아님.
            # TODO: 부분 취소 시 라인별 재고 복구 정책 미정.
            payment.status = PaymentStatus.PARTIAL_CANCELLED
        elif status in (_TOSS_ABORTED, _TOSS_EXPIRED):
            payment.status = PaymentStatus.FAILED
            payment.fail_reason = f"토스 결제 상태: {status}"
            await self._restore_order_stock_and_cancel(payment.order_id)
        elif status in _TOSS_PENDING_STATUSES:
            # 아직 승인 전 — 확정 웹훅을 기다린다.
            logger.info(
                "웹훅 수신 — 확정 전 상태 %s, 대기: pg_tid=%s", status, payment.pg_tid
            )

    async def cancel_payment(
        self,
        order_id: int,
        *,
        reason: str,
        cancel_amount: int | None = None,
    ) -> None:
        """주문의 PAID 결제를 PG 에서 취소/환불한다. order 모듈이 취소·환불 시 호출.

        - PAID 결제가 없으면(결제 전 PENDING 주문, 이미 취소됨) 조용히 return — 멱등
        - PG 취소 성공 시 Payment 를 CANCELLED / PARTIAL_CANCELLED 로 전환
        - PG 거절/네트워크 오류는 예외가 전파돼 주문 취소 트랜잭션을 롤백시킨다
        """
        payments = await self._repo.get_by_order_id_with_lock(order_id)
        paid = next(
            (p for p in payments if p.status == PaymentStatus.PAID), None
        )
        if paid is None:
            return
        if not paid.pg_tid:
            raise PaymentFailedError("결제 거래 ID(pg_tid)가 없어 취소할 수 없습니다.")

        result = await self._gateway.cancel(
            payment_key=paid.pg_tid,
            reason=reason,
            cancel_amount=cancel_amount,
        )
        await self._repo.update_status_cancelled(paid, result)

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
