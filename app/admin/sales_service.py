"""관리자 매출 서비스."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin._query_helpers import TruncUnit, date_trunc_literal
from app.admin.sales_schemas import (
    PaymentMethodStat,
    SalesSummary,
    SalesTimeSeries,
    TopProductItem,
)
from app.catalog.models import Product
from app.order.models import Order, OrderItem, OrderStatus
from app.payment.models import Payment, PaymentStatus


class SalesService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_summary(self, from_dt: datetime, to_dt: datetime) -> SalesSummary:
        date_filter = [Order.created_at >= from_dt, Order.created_at <= to_dt]
        row = (
            await self._session.execute(
                select(
                    func.coalesce(
                        func.sum(Order.total_amount).filter(
                            Order.status != OrderStatus.CANCELLED
                        ),
                        0,
                    ).label("revenue"),
                    func.count(Order.id)
                    .filter(Order.status != OrderStatus.CANCELLED)
                    .label("order_count"),
                    func.count(Order.id)
                    .filter(Order.status == OrderStatus.CANCELLED)
                    .label("cancel_count"),
                ).where(*date_filter)
            )
        ).one()

        total = row.order_count + row.cancel_count
        return SalesSummary(
            total_revenue=row.revenue,
            order_count=row.order_count,
            avg_order_value=row.revenue // row.order_count if row.order_count else 0,
            cancel_rate=row.cancel_count / total if total else 0.0,
        )

    async def get_timeseries(
        self, from_dt: datetime, to_dt: datetime, granularity: str
    ) -> SalesTimeSeries:
        trunc: TruncUnit = "week" if granularity == "week" else "day"
        period_trunc = date_trunc_literal(trunc, Order.created_at)
        rows = (
            await self._session.execute(
                select(
                    period_trunc.label("period"),
                    func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
                    func.count(Order.id).label("order_count"),
                )
                .where(
                    Order.created_at >= from_dt,
                    Order.created_at <= to_dt,
                    Order.status != OrderStatus.CANCELLED,
                )
                .group_by(period_trunc)
                .order_by(period_trunc)
            )
        ).all()
        data = [
            {
                "date": row.period.strftime("%Y-%m-%d"),
                "revenue": row.revenue,
                "order_count": row.order_count,
            }
            for row in rows
        ]
        return SalesTimeSeries(granularity=granularity, data=data)

    async def get_by_payment_method(
        self, from_dt: datetime, to_dt: datetime
    ) -> list[PaymentMethodStat]:
        rows = (
            await self._session.execute(
                select(
                    Payment.method,
                    func.coalesce(func.sum(Payment.amount), 0).label("revenue"),
                    func.count(Payment.id).label("order_count"),
                )
                .join(Order, Payment.order_id == Order.id)
                .where(
                    Order.created_at >= from_dt,
                    Order.created_at <= to_dt,
                    Payment.status == PaymentStatus.PAID,
                )
                .group_by(Payment.method)
            )
        ).all()
        return [
            PaymentMethodStat(
                method=row.method,
                revenue=row.revenue,
                order_count=row.order_count,
            )
            for row in rows
        ]

    async def get_top_products(
        self, from_dt: datetime, to_dt: datetime, limit: int = 5
    ) -> list[TopProductItem]:
        rows = (
            await self._session.execute(
                select(
                    OrderItem.product_id,
                    Product.title,
                    func.sum(OrderItem.price_snapshot * OrderItem.quantity).label("revenue"),
                    func.sum(OrderItem.quantity).label("quantity_sold"),
                )
                .join(Order, OrderItem.order_id == Order.id)
                .join(Product, OrderItem.product_id == Product.id)
                .where(
                    Order.created_at >= from_dt,
                    Order.created_at <= to_dt,
                    Order.status != OrderStatus.CANCELLED,
                )
                .group_by(OrderItem.product_id, Product.title)
                .order_by(
                    func.sum(OrderItem.price_snapshot * OrderItem.quantity).desc()
                )
                .limit(limit)
            )
        ).all()
        return [
            TopProductItem(
                product_id=row.product_id,
                title=row.title,
                revenue=row.revenue,
                quantity_sold=row.quantity_sold,
            )
            for row in rows
        ]

    async def export_csv(self, from_dt: datetime, to_dt: datetime) -> str:
        orders = list(
            (
                await self._session.execute(
                    select(Order)
                    .where(Order.created_at >= from_dt, Order.created_at <= to_dt)
                    .order_by(Order.created_at.desc())
                )
            ).scalars()
        )
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["주문번호", "주문일시", "금액", "상태"])
        for o in orders:
            writer.writerow([
                o.order_number,
                o.created_at.strftime("%Y-%m-%d %H:%M"),
                o.total_amount,
                o.status.value,
            ])
        return buf.getvalue()
