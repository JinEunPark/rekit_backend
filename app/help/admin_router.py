"""help 모듈 어드민 Router — 공지사항/FAQ CRUD, 문의 관리."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import get_admin_help_service, get_admin_user
from app.help.models import ContactStatus
from app.help.schemas import (
    AdminContactDetail,
    AdminContactListResponse,
    AdminContactStatusUpdate,
    AdminFaqCreate,
    AdminFaqListResponse,
    AdminFaqResponse,
    AdminFaqUpdate,
    AdminNoticeCreate,
    AdminNoticeListResponse,
    AdminNoticeResponse,
    AdminNoticeUpdate,
)
from app.help.service import AdminHelpService

router = APIRouter(tags=["admin-help"], dependencies=[Depends(get_admin_user)])


# ── 공지사항 ─────────────────────────────────────────────────────────


@router.get(
    "/admin/notices",
    response_model=AdminNoticeListResponse,
    summary="공지사항 목록 (어드민, 비게시 포함)",
)
async def list_notices(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    service: AdminHelpService = Depends(get_admin_help_service),
) -> AdminNoticeListResponse:
    return await service.list_notices(page, size)


@router.post(
    "/admin/notices",
    response_model=AdminNoticeResponse,
    status_code=201,
    summary="공지사항 생성",
)
async def create_notice(
    body: AdminNoticeCreate,
    service: AdminHelpService = Depends(get_admin_help_service),
) -> AdminNoticeResponse:
    return await service.create_notice(body)


@router.patch(
    "/admin/notices/{notice_id}",
    response_model=AdminNoticeResponse,
    summary="공지사항 수정",
)
async def update_notice(
    notice_id: int,
    body: AdminNoticeUpdate,
    service: AdminHelpService = Depends(get_admin_help_service),
) -> AdminNoticeResponse:
    return await service.update_notice(notice_id, body)


@router.delete(
    "/admin/notices/{notice_id}",
    status_code=204,
    summary="공지사항 삭제",
)
async def delete_notice(
    notice_id: int,
    service: AdminHelpService = Depends(get_admin_help_service),
) -> None:
    await service.delete_notice(notice_id)


# ── FAQ ──────────────────────────────────────────────────────────────


@router.get(
    "/admin/faqs",
    response_model=AdminFaqListResponse,
    summary="FAQ 목록 (어드민, 비게시 포함)",
)
async def list_faqs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    category: Annotated[str | None, Query()] = None,
    service: AdminHelpService = Depends(get_admin_help_service),
) -> AdminFaqListResponse:
    return await service.list_faqs(page, size, category)


@router.post(
    "/admin/faqs",
    response_model=AdminFaqResponse,
    status_code=201,
    summary="FAQ 생성",
)
async def create_faq(
    body: AdminFaqCreate,
    service: AdminHelpService = Depends(get_admin_help_service),
) -> AdminFaqResponse:
    return await service.create_faq(body)


@router.patch(
    "/admin/faqs/{faq_id}",
    response_model=AdminFaqResponse,
    summary="FAQ 수정",
)
async def update_faq(
    faq_id: int,
    body: AdminFaqUpdate,
    service: AdminHelpService = Depends(get_admin_help_service),
) -> AdminFaqResponse:
    return await service.update_faq(faq_id, body)


@router.delete(
    "/admin/faqs/{faq_id}",
    status_code=204,
    summary="FAQ 삭제",
)
async def delete_faq(
    faq_id: int,
    service: AdminHelpService = Depends(get_admin_help_service),
) -> None:
    await service.delete_faq(faq_id)


# ── 문의 관리 ────────────────────────────────────────────────────────


@router.get(
    "/admin/contacts",
    response_model=AdminContactListResponse,
    summary="문의 목록",
)
async def list_contacts(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: Annotated[ContactStatus | None, Query()] = None,
    service: AdminHelpService = Depends(get_admin_help_service),
) -> AdminContactListResponse:
    return await service.list_contacts(page, size, status)


@router.get(
    "/admin/contacts/{contact_id}",
    response_model=AdminContactDetail,
    summary="문의 상세",
)
async def get_contact(
    contact_id: int,
    service: AdminHelpService = Depends(get_admin_help_service),
) -> AdminContactDetail:
    return await service.get_contact(contact_id)


@router.patch(
    "/admin/contacts/{contact_id}/status",
    response_model=AdminContactDetail,
    summary="문의 상태 변경 (PENDING → ANSWERED)",
)
async def update_contact_status(
    contact_id: int,
    body: AdminContactStatusUpdate,
    service: AdminHelpService = Depends(get_admin_help_service),
) -> AdminContactDetail:
    return await service.update_contact_status(contact_id, body)
