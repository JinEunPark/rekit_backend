"""help 모듈 공개 Router — 공지사항, FAQ, 문의하기."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import get_help_service
from app.help.schemas import (
    ContactRequest,
    FaqListResponse,
    NoticeDetail,
    NoticeListResponse,
)
from app.help.service import HelpService

router = APIRouter(prefix="/help", tags=["help"])


# ── 공지사항 ─────────────────────────────────────────────────────────


@router.get("/notices", response_model=NoticeListResponse, summary="공지사항 목록")
async def list_notices(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    service: HelpService = Depends(get_help_service),
) -> NoticeListResponse:
    return await service.list_notices(page, size)


@router.get("/notices/{notice_id}", response_model=NoticeDetail, summary="공지사항 상세")
async def get_notice(
    notice_id: int,
    service: HelpService = Depends(get_help_service),
) -> NoticeDetail:
    return await service.get_notice(notice_id)


# ── FAQ ──────────────────────────────────────────────────────────────


@router.get("/faqs", response_model=FaqListResponse, summary="FAQ 목록")
async def list_faqs(
    category: Annotated[
        str | None, Query(description="카테고리 필터 (예: 주문, 배송, 결제, 회원, 기타)")
    ] = None,
    service: HelpService = Depends(get_help_service),
) -> FaqListResponse:
    return await service.list_faqs(category)


# ── 문의하기 ─────────────────────────────────────────────────────────


@router.post("/contact", status_code=204, summary="1:1 문의 접수")
async def submit_contact(
    body: ContactRequest,
    service: HelpService = Depends(get_help_service),
) -> None:
    await service.submit_contact(body)
