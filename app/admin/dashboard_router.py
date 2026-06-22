"""관리자 대시보드 Router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.admin.dashboard_schemas import (
    CategoryStat,
    DashboardSummary,
    PendingOrderItem,
    SalesChart,
    StockAlertItem,
)
from app.admin.dashboard_service import DashboardService
from app.core.deps import get_admin_user, get_dashboard_service
from app.user.models import User

router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"])


@router.get("/summary", response_model=DashboardSummary, summary="대시보드 KPI 요약")
async def get_summary(
    _: User = Depends(get_admin_user),
    service: DashboardService = Depends(get_dashboard_service),
) -> DashboardSummary:
    return await service.get_summary()


@router.get("/sales-chart", response_model=SalesChart, summary="기간별 매출 차트")
async def get_sales_chart(
    period: str = Query(default="7d", pattern="^(7d|30d|90d)$"),
    _: User = Depends(get_admin_user),
    service: DashboardService = Depends(get_dashboard_service),
) -> SalesChart:
    return await service.get_sales_chart(period)


@router.get(
    "/pending-orders",
    response_model=list[PendingOrderItem],
    summary="처리 대기 주문 목록",
)
async def get_pending_orders(
    limit: int = Query(default=4, ge=1, le=20),
    _: User = Depends(get_admin_user),
    service: DashboardService = Depends(get_dashboard_service),
) -> list[PendingOrderItem]:
    return await service.get_pending_orders(limit)


@router.get(
    "/popular-categories",
    response_model=list[CategoryStat],
    summary="인기 카테고리",
)
async def get_popular_categories(
    _: User = Depends(get_admin_user),
    service: DashboardService = Depends(get_dashboard_service),
) -> list[CategoryStat]:
    return await service.get_popular_categories()


@router.get(
    "/stock-alerts",
    response_model=list[StockAlertItem],
    summary="재고 부족 상품 (stock ≤ 3)",
)
async def get_stock_alerts(
    _: User = Depends(get_admin_user),
    service: DashboardService = Depends(get_dashboard_service),
) -> list[StockAlertItem]:
    return await service.get_stock_alerts()
