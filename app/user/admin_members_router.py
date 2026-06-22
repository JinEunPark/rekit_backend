"""관리자 회원 관리 Router."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import get_admin_members_service, get_admin_user
from app.user.admin_members_schemas import (
    AdminMemberDetail,
    AdminMemberListParams,
    AdminMemberListResponse,
    AdminMemberStatusUpdate,
    AdminMemberSummary,
)
from app.user.admin_members_service import AdminMembersService
from app.user.models import User

router = APIRouter(prefix="/admin/members", tags=["admin-members"])


@router.get("/summary", response_model=AdminMemberSummary, summary="회원 KPI 요약")
async def get_summary(
    _: User = Depends(get_admin_user),
    service: AdminMembersService = Depends(get_admin_members_service),
) -> AdminMemberSummary:
    return await service.get_summary()


@router.get("", response_model=AdminMemberListResponse, summary="회원 목록")
async def list_members(
    params: Annotated[AdminMemberListParams, Depends()],
    _: User = Depends(get_admin_user),
    service: AdminMembersService = Depends(get_admin_members_service),
) -> AdminMemberListResponse:
    return await service.list_members(params)


@router.get("/{member_id}", response_model=AdminMemberDetail, summary="회원 상세")
async def get_member(
    member_id: int,
    _: User = Depends(get_admin_user),
    service: AdminMembersService = Depends(get_admin_members_service),
) -> AdminMemberDetail:
    return await service.get_member(member_id)


@router.patch(
    "/{member_id}/status",
    response_model=AdminMemberDetail,
    summary="회원 상태 변경 (활성/정지/휴면)",
)
async def update_status(
    member_id: int,
    body: AdminMemberStatusUpdate,
    _: User = Depends(get_admin_user),
    service: AdminMembersService = Depends(get_admin_members_service),
) -> AdminMemberDetail:
    return await service.update_status(member_id, body)
