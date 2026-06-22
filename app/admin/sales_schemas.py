"""관리자 매출 Pydantic 스키마."""

from __future__ import annotations

from pydantic import BaseModel

from app.payment.models import PaymentMethod


class SalesSummary(BaseModel):
    total_revenue: int
    order_count: int
    avg_order_value: int
    cancel_rate: float


class SalesTimeSeries(BaseModel):
    granularity: str
    data: list[dict]


class PaymentMethodStat(BaseModel):
    method: PaymentMethod
    revenue: int
    order_count: int


class TopProductItem(BaseModel):
    product_id: int
    title: str
    revenue: int
    quantity_sold: int
