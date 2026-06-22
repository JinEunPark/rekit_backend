"""관리자 매출 Router."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.admin.sales_schemas import (
    PaymentMethodStat,
    SalesSummary,
    SalesTimeSeries,
    TopProductItem,
)
from app.admin.sales_service import SalesService
from app.core.deps import get_admin_user, get_sales_service
from app.user.models import User

router = APIRouter(prefix="/admin/sales", tags=["admin-sales"])


def _parse_range(
    from_date: str | None, to_date: str | None
) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    from_dt = (
        datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=UTC)
        if from_date
        else now - timedelta(days=30)
    )
    to_dt = (
        datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=UTC)
        if to_date
        else now
    )
    if from_dt > to_dt:
        raise HTTPException(status_code=422, detail="from_date는 to_date보다 이전이어야 합니다.")
    return from_dt, to_dt


@router.get("/summary", response_model=SalesSummary, summary="매출 요약")
async def get_summary(
    from_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    to_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    _: User = Depends(get_admin_user),
    service: SalesService = Depends(get_sales_service),
) -> SalesSummary:
    from_dt, to_dt = _parse_range(from_date, to_date)
    return await service.get_summary(from_dt, to_dt)


@router.get("/timeseries", response_model=SalesTimeSeries, summary="매출 시계열")
async def get_timeseries(
    granularity: str = Query(default="day", pattern="^(day|week)$"),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    _: User = Depends(get_admin_user),
    service: SalesService = Depends(get_sales_service),
) -> SalesTimeSeries:
    from_dt, to_dt = _parse_range(from_date, to_date)
    return await service.get_timeseries(from_dt, to_dt, granularity)


@router.get(
    "/by-payment-method",
    response_model=list[PaymentMethodStat],
    summary="결제수단별 매출",
)
async def get_by_payment_method(
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    _: User = Depends(get_admin_user),
    service: SalesService = Depends(get_sales_service),
) -> list[PaymentMethodStat]:
    from_dt, to_dt = _parse_range(from_date, to_date)
    return await service.get_by_payment_method(from_dt, to_dt)


@router.get("/top-products", response_model=list[TopProductItem], summary="매출 상위 상품")
async def get_top_products(
    limit: int = Query(default=5, ge=1, le=20),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    _: User = Depends(get_admin_user),
    service: SalesService = Depends(get_sales_service),
) -> list[TopProductItem]:
    from_dt, to_dt = _parse_range(from_date, to_date)
    return await service.get_top_products(from_dt, to_dt, limit)


@router.get("/export.csv", summary="매출 CSV 내보내기")
async def export_csv(
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    _: User = Depends(get_admin_user),
    service: SalesService = Depends(get_sales_service),
) -> StreamingResponse:
    from_dt, to_dt = _parse_range(from_date, to_date)
    content = await service.export_csv(from_dt, to_dt)
    return StreamingResponse(
        iter([content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sales.csv"},
    )
