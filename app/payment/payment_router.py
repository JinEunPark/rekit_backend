"""payment 모듈 Router — /payments prefix.

api.md 결제 API:
- POST /payments/init          : 결제창 열기 전 초기화 (인증 필요)
- POST /payments/confirm       : 토스 성공 콜백 후 confirm (인증 필요)
- POST /payments/webhooks/toss : 토스 웹훅 수신 (인증 불필요, 수신 후 조회 API 로 재검증)
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, status

from app.core.deps import get_active_user, get_payment_service
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
    body: TossWebhookPayload,
    service: PaymentService = Depends(get_payment_service),
) -> dict[str, str]:
    """토스 PG 웹훅 수신 엔드포인트 (인증 없음).

    토스 결제 웹훅에는 서명이 없다 (`tosspayments-webhook-signature` 는 지급대행
    이벤트 전용). 대신 서비스가 paymentKey 로 결제 조회 API 를 호출해 실제 상태를
    재확인하므로, 위조된 body 로는 상태를 바꿀 수 없다.

    조회 실패 시 PaymentGatewayUnknownError(502) 가 전파되고 토스가 재시도한다.
    """
    await service.handle_webhook(body)
    return {"status": "ok"}
