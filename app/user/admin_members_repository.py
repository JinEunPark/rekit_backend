"""관리자 회원 Repository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, NamedTuple

from sqlalchemy import Subquery, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.order.models import Order, OrderStatus
from app.user.models import User

if TYPE_CHECKING:
    from app.user.admin_members_schemas import AdminMemberListParams


class MemberRow(NamedTuple):
    user: User
    order_count: int
    total_purchased: int


class AdminMembersRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _order_agg_subquery(self) -> Subquery:
        return (
            select(
                Order.user_id,
                func.count(Order.id).label("order_count"),
                func.coalesce(func.sum(Order.total_amount), 0).label("total_purchased"),
            )
            .where(Order.status != OrderStatus.CANCELLED)
            .group_by(Order.user_id)
            .subquery()
        )

    async def summary(self) -> dict[str, int]:
        now = datetime.now(UTC)
        week_start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # User 테이블 집계 3개를 단일 쿼리로
        row = (
            await self._session.execute(
                select(
                    func.count(User.id).label("total"),
                    func.count(User.id)
                    .filter(User.identity_verified_at.is_not(None))
                    .label("verified"),
                    func.count(User.id)
                    .filter(User.created_at >= week_start)
                    .label("new_this_week"),
                )
            )
        ).one()

        purchased_sq = select(Order.user_id).distinct().subquery()
        purchased: int = (
            await self._session.execute(select(func.count()).select_from(purchased_sq))
        ).scalar_one()

        return {
            "total": row.total,
            "verified": row.verified,
            "new_this_week": row.new_this_week,
            "purchased": purchased,
        }

    async def get_list(
        self, params: AdminMemberListParams
    ) -> tuple[list[MemberRow], int]:
        order_agg = self._order_agg_subquery()

        base = (
            select(
                User,
                func.coalesce(order_agg.c.order_count, 0).label("order_count"),
                func.coalesce(order_agg.c.total_purchased, 0).label("total_purchased"),
            )
            .outerjoin(order_agg, User.id == order_agg.c.user_id)
        )

        if params.status is not None:
            base = base.where(User.status == params.status)
        if params.q:
            pattern = f"%{params.q}%"
            base = base.where(
                or_(
                    User.username.ilike(pattern),
                    User.email.ilike(pattern),
                    User.phone.ilike(pattern),
                    User.login_id.ilike(pattern),
                )
            )

        total: int = (
            await self._session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()

        base = (
            base.order_by(User.created_at.desc())
            .offset((params.page - 1) * params.size)
            .limit(params.size)
        )
        rows = (await self._session.execute(base)).all()
        return [MemberRow(row[0], row.order_count, row.total_purchased) for row in rows], total

    async def get_by_id(self, member_id: int) -> MemberRow | None:
        order_agg = self._order_agg_subquery()
        stmt = (
            select(
                User,
                func.coalesce(order_agg.c.order_count, 0).label("order_count"),
                func.coalesce(order_agg.c.total_purchased, 0).label("total_purchased"),
            )
            .outerjoin(order_agg, User.id == order_agg.c.user_id)
            .where(User.id == member_id)
        )
        row = (await self._session.execute(stmt)).first()
        if row is None:
            return None
        return MemberRow(row[0], row.order_count, row.total_purchased)

    async def get_user(self, member_id: int) -> User | None:
        return (
            await self._session.execute(select(User).where(User.id == member_id))
        ).scalar_one_or_none()
