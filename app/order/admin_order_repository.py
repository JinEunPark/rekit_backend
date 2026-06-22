"""관리자 주문 Repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.order.models import Order, OrderStatus
from app.order.shipment import Shipment, ShipmentStatus
from app.user.models import User

if TYPE_CHECKING:
    from app.order.admin_order_schemas import AdminOrderListParams


class AdminOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def status_counts(self) -> dict[str, int]:
        rows = (
            await self._session.execute(
                select(Order.status, func.count(Order.id)).group_by(Order.status)
            )
        ).all()
        counts: dict[str, int] = {s.value: 0 for s in OrderStatus}
        for row_status, cnt in rows:
            counts[row_status.value] = cnt
        return counts

    async def get_list(
        self, params: AdminOrderListParams
    ) -> tuple[list[Order], int]:
        base = (
            select(Order)
            .join(User, Order.user_id == User.id)
        )
        if params.status is not None:
            base = base.where(Order.status == params.status)
        if params.q:
            pattern = f"%{params.q}%"
            base = base.where(
                or_(
                    Order.order_number.ilike(pattern),
                    User.username.ilike(pattern),
                )
            )

        total: int = (
            await self._session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()

        base = (
            base.order_by(Order.created_at.desc())
            .offset((params.page - 1) * params.size)
            .limit(params.size)
            .options(selectinload(Order.items), selectinload(Order.user))
        )
        orders = list((await self._session.execute(base)).scalars())
        return orders, total

    async def get_by_order_number(self, order_number: str) -> Order | None:
        stmt = (
            select(Order)
            .where(Order.order_number == order_number)
            .options(
                selectinload(Order.items),
                selectinload(Order.user),
                selectinload(Order.shipment),
                selectinload(Order.payments),
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_order_for_update(self, order_number: str) -> Order | None:
        return (
            await self._session.execute(
                select(Order).where(Order.order_number == order_number)
            )
        ).scalar_one_or_none()

    async def create_or_update_shipment(
        self, order: Order, carrier: str, tracking_number: str
    ) -> None:
        now = datetime.now(UTC)
        await self._session.refresh(order, attribute_names=["shipment"])
        if order.shipment is not None:
            order.shipment.carrier = carrier
            order.shipment.tracking_number = tracking_number
            order.shipment.status = ShipmentStatus.IN_TRANSIT
            order.shipment.shipped_at = now
        else:
            self._session.add(Shipment(
                order_id=order.id,
                method=order.shipping_method,
                carrier=carrier,
                tracking_number=tracking_number,
                status=ShipmentStatus.IN_TRANSIT,
                shipped_at=now,
            ))
        await self._session.flush()
