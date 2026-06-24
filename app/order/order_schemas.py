"""order 모듈 Pydantic 스키마.

요청(Request) / 응답(Response) DTO 를 정의한다.
서비스 레이어는 이 스키마를 입출력으로 사용하며, ORM 모델에 직접 의존하지 않는다.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.pagination import PageMeta
from app.order.models import OrderStatus
from app.order.shipment import ShipmentMethod, ShipmentStatus

# ── 요청 스키마 ──────────────────────────────────────────────────────


class OrderItemRequest(BaseModel):
    """주문 라인 요청. quantity 는 1~10 제한 (중고 가전 특성상 대량 구매 불필요)."""

    product_id: int
    quantity: int = Field(ge=1, le=10)


class QuoteRequest(BaseModel):
    """배송비 견적 요청. 실제 주문 생성 전 금액 미리 보기."""

    items: list[OrderItemRequest]
    address_id: int
    shipping_method: ShipmentMethod


class CreateOrderRequest(BaseModel):
    """주문 생성 요청."""

    items: list[OrderItemRequest]
    address_id: int
    shipping_method: ShipmentMethod
    memo: str | None = None


# ── 응답 스키마 ──────────────────────────────────────────────────────


class OrderItemResponse(BaseModel):
    """주문 라인 응답. subtotal 은 서비스에서 계산해 채운다."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_title_snapshot: str
    product_image_url_snapshot: str | None
    price_snapshot: int
    quantity: int
    subtotal: int  # price_snapshot * quantity (서비스에서 계산)


class QuoteResponse(BaseModel):
    """배송비 견적 응답."""

    items_total: int
    shipping_fee: int
    discount_amount: int
    total_amount: int
    shipping_method: ShipmentMethod
    direct_available: bool  # 해당 주소에서 DIRECT 선택 가능 여부


class OrderResponse(BaseModel):
    """주문 단건 응답."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_number: str
    status: OrderStatus
    total_amount: int
    shipping_fee: int
    discount_amount: int
    shipping_method: ShipmentMethod
    recipient_name: str
    recipient_phone: str
    address1: str
    address2: str | None
    memo: str | None
    items: list[OrderItemResponse]
    paid_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime


class OrderListResponse(BaseModel):
    """주문 목록 응답 (페이지네이션 포함)."""

    items: list[OrderResponse]
    meta: PageMeta


class ShipmentResponse(BaseModel):
    """GET /orders/{order_number}/shipment 응답."""

    model_config = ConfigDict(from_attributes=True)

    method: ShipmentMethod
    status: ShipmentStatus
    carrier: str | None
    tracking_number: str | None
    shipped_at: datetime | None
    delivered_at: datetime | None


