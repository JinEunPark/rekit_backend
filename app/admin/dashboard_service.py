"""관리자 대시보드 서비스."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin._query_helpers import date_trunc_literal
from app.admin.dashboard_schemas import (
    CategoryStat,
    DashboardSummary,
    PendingOrderItem,
    SalesChart,
    SalesDataPoint,
    StockAlertItem,
)
from app.catalog.models import Product, ProductStatus
from app.order.models import Order, OrderItem, OrderStatus
from app.user.models import User


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_summary(self) -> DashboardSummary:
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        today_orders: int = (
            await self._session.execute(
                select(func.count(Order.id)).where(Order.created_at >= today_start)
            )
        ).scalar_one()

        today_revenue: int = (
            await self._session.execute(
                select(func.coalesce(func.sum(Order.total_amount), 0)).where(
                    Order.created_at >= today_start,
                    Order.status != OrderStatus.CANCELLED,
                )
            )
        ).scalar_one()

        pending_count: int = (
            await self._session.execute(
                select(func.count(Order.id)).where(
                    Order.status.in_([OrderStatus.PAID, OrderStatus.PREPARING])
                )
            )
        ).scalar_one()

        low_stock_count: int = (
            await self._session.execute(
                select(func.count(Product.id)).where(
                    Product.status == ProductStatus.ACTIVE,
                    Product.stock <= 3,
                )
            )
        ).scalar_one()

        return DashboardSummary(
            today_orders=today_orders,
            today_revenue=today_revenue,
            pending_count=pending_count,
            low_stock_count=low_stock_count,
        )

    async def get_sales_chart(self, period: str) -> SalesChart:
        days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 7)
        now = datetime.now(UTC)
        start = (now - timedelta(days=days)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        day_trunc = date_trunc_literal("day", Order.created_at)

        rows = (
            await self._session.execute(
                select(
                    day_trunc.label("day"),
                    func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
                    func.count(Order.id).label("order_count"),
                )
                .where(
                    Order.created_at >= start,
                    Order.status != OrderStatus.CANCELLED,
                )
                .group_by(day_trunc)
                .order_by(day_trunc)
            )
        ).all()

        data = [
            SalesDataPoint(
                date=row.day.strftime("%Y-%m-%d"),
                revenue=row.revenue,
                order_count=row.order_count,
            )
            for row in rows
        ]
        return SalesChart(period=period, data=data)

    async def get_pending_orders(self, limit: int = 4) -> list[PendingOrderItem]:
        rows = (
            await self._session.execute(
                select(Order, User.username)
                .join(User, Order.user_id == User.id)
                .where(Order.status.in_([OrderStatus.PAID, OrderStatus.PREPARING]))
                .order_by(Order.created_at.asc())
                .limit(limit)
            )
        ).all()
        return [
            PendingOrderItem(
                order_number=row[0].order_number,
                created_at=row[0].created_at,
                username=row[1],
                total_amount=row[0].total_amount,
                status=row[0].status,
            )
            for row in rows
        ]

    async def get_popular_categories(self) -> list[CategoryStat]:
        rows = (
            await self._session.execute(
                select(
                    Product.category.label("category"),
                    func.count(OrderItem.id).label("order_count"),
                    func.coalesce(
                        func.sum(OrderItem.price_snapshot * OrderItem.quantity), 0
                    ).label("revenue"),
                )
                .join(OrderItem, Product.id == OrderItem.product_id)
                .join(Order, OrderItem.order_id == Order.id)
                .where(Order.status != OrderStatus.CANCELLED)
                .group_by(Product.category)
                .order_by(func.count(OrderItem.id).desc())
                .limit(8)
            )
        ).all()
        return [
            CategoryStat(
                category=row.category,
                order_count=row.order_count,
                revenue=row.revenue,
            )
            for row in rows
        ]

    async def get_stock_alerts(self) -> list[StockAlertItem]:
        rows = (
            await self._session.execute(
                select(Product)
                .where(Product.status == ProductStatus.ACTIVE, Product.stock <= 3)
                .order_by(Product.stock.asc(), Product.id.asc())
                .limit(20)
            )
        ).scalars().all()
        return [
            StockAlertItem(
                product_id=p.id,
                title=p.title,
                brand=p.brand,
                stock=p.stock,
                category=p.category,
            )
            for p in rows
        ]
