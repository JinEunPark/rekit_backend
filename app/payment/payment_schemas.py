"""payment 모듈 Pydantic 스키마 — 요청/응답 DTO."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.payment.models import PaymentMethod, PaymentStatus


class PaymentInitRequest(BaseModel):
    """POST /payments/init — 결제창 열기 전 초기화."""

    order_number: str
    method: PaymentMethod


class PaymentInitResponse(BaseModel):
    """결제창 띄우는 데 필요한 데이터. 토스 SDK 가 이 값들로 위젯을 생성한다."""

    payment_id: int
    order_number: str
    amount: int
    customer_name: str  # 토스 결제창 표시용 (order.user.username)


class PaymentConfirmRequest(BaseModel):
    """POST /payments/confirm — 프론트에서 토스 성공 콜백 후 호출.

    토스 SDK 가 success redirect 시 query string 으로 paymentKey, orderId, amount
    를 전달한다. 프론트가 이 값을 그대로 body 에 실어 서버로 보낸다.
    """

    payment_key: str  # 토스 paymentKey
    order_id: str  # order_number (토스가 orderId로 부름)
    amount: int


class PaymentConfirmResponse(BaseModel):
    """confirm 성공 응답. 영수증 표시에 필요한 카드 정보 포함."""

    order_number: str
    status: PaymentStatus
    paid_at: datetime | None
    card_company: str | None
    card_last4: str | None
    installment_months: int | None


class TossWebhookPayload(BaseModel):
    """POST /payments/webhooks/toss — 토스 웹훅 바디."""

    model_config = ConfigDict(populate_by_name=True)

    event_type: str = Field(alias="eventType")
    data: dict[str, Any]


class PaymentResponse(BaseModel):
    """결제 조회 응답 — ORM 모델에서 직접 변환."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    method: PaymentMethod
    amount: int
    status: PaymentStatus
    paid_at: datetime | None
    card_company: str | None
    card_last4: str | None
    installment_months: int | None
