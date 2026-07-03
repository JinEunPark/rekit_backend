"""payment 모듈 Router — /payments prefix.

api.md 결제 API:
- POST /payments/init          : 결제창 열기 전 초기화 (인증 필요)
- POST /payments/confirm       : 토스 성공 콜백 후 confirm (인증 필요)
- POST /payments/webhooks/toss : 토스 웹훅 수신 (인증 불필요, HMAC 서명 검증)
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status

from app.core.deps import get_active_user, get_payment_service
from app.core.exceptions import PaymentFailedError
from app.payment.payment_schemas import (
    PaymentConfirmRequest,
    PaymentConfirmResponse,
    PaymentInitRequest,
    PaymentInitResponse,
    TossWebhookPayload,
)
from app.payment.payment_service import PaymentService
from app.user.models import User

router = APIRouter(prefix="/payments", tags=["payments"])


# ── 엔드포인트 ────────────────────────────────────────────────────────


@router.post(
    "/init",
    response_model=PaymentInitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="결제 초기화",
)
async def init_payment(
    body: PaymentInitRequest,
    user: User = Depends(get_active_user),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentInitResponse:
    """결제창 열기 전 Payment(READY) 생성.

    Errors:
    - ORDER_NOT_FOUND (404): 주문이 없거나 본인 주문이 아님
    - PAYMENT_FAILED (422): 주문 상태가 PENDING 이 아님
    """
    return await service.init_payment(user.id, body)


@router.post(
    "/confirm",
    response_model=PaymentConfirmResponse,
    status_code=status.HTTP_200_OK,
    summary="결제 confirm",
    dependencies=[Depends(get_active_user)],
)
async def confirm_payment(
    body: PaymentConfirmRequest,
    background_tasks: BackgroundTasks,
    service: PaymentService = Depends(get_payment_service),
) -> PaymentConfirmResponse:
    """토스 성공 콜백 후 서버↔PG 최종 검증.

    Errors:
    - ORDER_NOT_FOUND (404): 주문 없음
    - PAYMENT_FAILED (422): READY 결제 없음 / 금액 불일치 / PG 거절
    """
    return await service.confirm_payment(body, background_tasks)


@router.post(
    "/webhooks/toss",
    status_code=status.HTTP_200_OK,
    summary="토스 웹훅",
)
async def toss_webhook(
    request: Request,
    body: TossWebhookPayload,
    service: PaymentService = Depends(get_payment_service),
) -> dict[str, str]:
    """토스 PG 웹훅 수신 엔드포인트. 인증 없이 HMAC 서명으로 검증.

    서명 실패 시 400 반환 — 토스는 400/500 응답 시 재시도하므로
    서명 오류는 재시도 없도록 400 으로 즉시 거절.
    """
    raw_body = await request.body()
    signature = request.headers.get("TossPayments-Signature", "")

    if not service.verify_webhook(raw_body, signature):
        raise PaymentFailedError("웹훅 서명 검증 실패")

    await service.handle_webhook(body)
    return {"status": "ok"}
