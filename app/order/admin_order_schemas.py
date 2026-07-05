"""관리자 주문 관리 Pydantic 스키마."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.pagination import PageMeta
from app.order.models import OrderStatus
from app.order.shipment import ShipmentMethod, ShipmentStatus


class AdminOrderListParams(BaseModel):
    status: OrderStatus | None = None
    q: str | None = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


class AdminOrderStatusCounts(BaseModel):
    all: int
    paid: int
    preparing: int
    shipping: int
    delivered: int
    cancelled: int


class AdminOrderItemSummary(BaseModel):
    product_id: int
    product_title_snapshot: str
    product_brand_snapshot: str | None
    product_model_name_snapshot: str | None
    product_image_url_snapshot: str | None
    quantity: int
    price_snapshot: int


class AdminOrderListItem(BaseModel):
    order_number: str
    created_at: datetime
    username: str
    recipient_phone: str
    item_count: int
    first_item_title: str
    total_amount: int
    status: OrderStatus
    shipping_method: ShipmentMethod


class AdminOrderListResponse(BaseModel):
    items: list[AdminOrderListItem]
    counts: AdminOrderStatusCounts
    meta: PageMeta


class AdminShipmentInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    carrier: str | None
    tracking_number: str | None
    status: ShipmentStatus
    shipped_at: datetime | None
    delivered_at: datetime | None


class AdminOrderDetail(BaseModel):
    order_number: str
    created_at: datetime
    status: OrderStatus
    shipping_method: ShipmentMethod
    total_amount: int
    shipping_fee: int
    discount_amount: int
    memo: str | None
    user_id: int
    username: str
    email: str
    recipient_name: str
    recipient_phone: str
    zipcode: str
    address1: str
    address2: str | None
    items: list[AdminOrderItemSummary]
    payment_method: str | None
    paid_at: datetime | None
    cancelled_at: datetime | None
    shipment: AdminShipmentInfo | None


class AdminShipmentInput(BaseModel):
    carrier: str = Field(min_length=1, max_length=50)
    tracking_number: str = Field(min_length=1, max_length=50)


class AdminOrderStatusUpdate(BaseModel):
    status: OrderStatus


class AdminOrderCancelRequest(BaseModel):
    reason: str | None = None
