"""관리자 대시보드 Pydantic 스키마."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.order.models import OrderStatus


class DashboardSummary(BaseModel):
    today_orders: int
    today_revenue: int
    pending_count: int
    low_stock_count: int


class SalesDataPoint(BaseModel):
    date: str
    revenue: int
    order_count: int


class SalesChart(BaseModel):
    period: str
    data: list[SalesDataPoint]


class PendingOrderItem(BaseModel):
    order_number: str
    created_at: datetime
    username: str
    total_amount: int
    status: OrderStatus


class CategoryStat(BaseModel):
    category: str
    order_count: int
    revenue: int


class StockAlertItem(BaseModel):
    product_id: int
    title: str
    brand: str | None
    stock: int
    category: str
