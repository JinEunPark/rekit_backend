"""관리자 회원 서비스."""

from __future__ import annotations

from app.core.exceptions import UserNotFoundError
from app.core.pagination import build_page_meta
from app.user.admin_members_repository import AdminMembersRepository, MemberRow
from app.user.admin_members_schemas import (
    AdminMemberDetail,
    AdminMemberItem,
    AdminMemberListParams,
    AdminMemberListResponse,
    AdminMemberStatusUpdate,
    AdminMemberSummary,
)
from app.user.models import UserStatus


def _to_member_item(row: MemberRow) -> AdminMemberItem:
    return AdminMemberItem(
        id=row.user.id,
        login_id=row.user.login_id,
        username=row.user.username,
        email=row.user.email,
        phone=row.user.phone,
        role=row.user.role,
        status=row.user.status,
        is_active=row.user.is_active,
        verified=row.user.verified,
        created_at=row.user.created_at,
        order_count=row.order_count,
        total_purchased=row.total_purchased,
    )


def _to_member_detail(row: MemberRow) -> AdminMemberDetail:
    return AdminMemberDetail(
        id=row.user.id,
        login_id=row.user.login_id,
        username=row.user.username,
        email=row.user.email,
        phone=row.user.phone,
        role=row.user.role,
        status=row.user.status,
        is_active=row.user.is_active,
        verified=row.user.verified,
        created_at=row.user.created_at,
        order_count=row.order_count,
        total_purchased=row.total_purchased,
        phone_verified_at=row.user.phone_verified_at,
        agreed_marketing_at=row.user.agreed_marketing_at,
    )


class AdminMembersService:
    def __init__(self, repo: AdminMembersRepository) -> None:
        self._repo = repo

    async def get_summary(self) -> AdminMemberSummary:
        data = await self._repo.summary()
        return AdminMemberSummary(**data)

    async def list_members(self, params: AdminMemberListParams) -> AdminMemberListResponse:
        rows, total = await self._repo.get_list(params)
        return AdminMemberListResponse(
            items=[_to_member_item(r) for r in rows],
            meta=build_page_meta(total, params.page, params.size),
        )

    async def get_member(self, member_id: int) -> AdminMemberDetail:
        row = await self._repo.get_by_id(member_id)
        if row is None:
            raise UserNotFoundError()
        return _to_member_detail(row)

    async def update_status(
        self, member_id: int, body: AdminMemberStatusUpdate
    ) -> AdminMemberDetail:
        user = await self._repo.get_user(member_id)
        if user is None:
            raise UserNotFoundError()
        user.status = body.status
        user.is_active = body.status == UserStatus.ACTIVE
        row = await self._repo.get_by_id(member_id)
        return _to_member_detail(row)  # type: ignore[arg-type]
