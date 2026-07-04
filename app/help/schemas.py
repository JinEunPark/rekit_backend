"""help 모듈 Pydantic 스키마 — 공지사항, FAQ, 문의하기 요청/응답 DTO."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.pagination import PageMeta
from app.help.models import ContactStatus


class _OrmBase(BaseModel):
    """ORM 매핑이 필요한 응답 스키마 공용 베이스."""

    model_config = ConfigDict(from_attributes=True)


# ── 공지사항 ─────────────────────────────────────────────────────────


class NoticeListItem(_OrmBase):
    id: int
    title: str
    is_pinned: bool
    created_at: datetime


class NoticeDetail(_OrmBase):
    id: int
    title: str
    content: str
    is_pinned: bool
    created_at: datetime
    updated_at: datetime


class AdminNoticeResponse(NoticeDetail):
    """NoticeDetail + is_published (관리자 전용)."""

    is_published: bool


class NoticeListResponse(BaseModel):
    items: list[NoticeListItem]
    meta: PageMeta


class AdminNoticeListResponse(BaseModel):
    items: list[AdminNoticeResponse]
    meta: PageMeta


# ── 공지사항 요청 ─────────────────────────────────────────────────────


class AdminNoticeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    is_pinned: bool = False
    is_published: bool = True


class AdminNoticeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1)
    is_pinned: bool | None = None
    is_published: bool | None = None


# ── FAQ ──────────────────────────────────────────────────────────────


class FaqItem(_OrmBase):
    id: int
    category: str
    question: str
    answer: str
    sort_order: int


class AdminFaqResponse(FaqItem):
    """FaqItem + is_published, 타임스탬프 (관리자 전용)."""

    is_published: bool
    created_at: datetime
    updated_at: datetime


class FaqListResponse(BaseModel):
    items: list[FaqItem]


class AdminFaqListResponse(BaseModel):
    items: list[AdminFaqResponse]
    meta: PageMeta


# ── FAQ 요청 ──────────────────────────────────────────────────────────


class AdminFaqCreate(BaseModel):
    category: str = Field(min_length=1, max_length=50)
    question: str = Field(min_length=1, max_length=300)
    answer: str = Field(min_length=1)
    sort_order: int = Field(default=0, ge=0)
    is_published: bool = True


class AdminFaqUpdate(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=50)
    question: str | None = Field(default=None, min_length=1, max_length=300)
    answer: str | None = Field(default=None, min_length=1)
    sort_order: int | None = Field(default=None, ge=0)
    is_published: bool | None = None


# ── 문의하기 ─────────────────────────────────────────────────────────


class ContactRequest(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=10, max_length=3000)


class ContactListItem(_OrmBase):
    id: int
    title: str
    status: ContactStatus
    answered_at: datetime | None
    created_at: datetime


class ContactDetail(_OrmBase):
    id: int
    title: str
    content: str
    status: ContactStatus
    answered_at: datetime | None
    answer_content: str | None
    created_at: datetime


class ContactListResponse(BaseModel):
    items: list[ContactListItem]
    meta: PageMeta


class AdminContactListItem(_OrmBase):
    id: int
    name: str
    email: str
    title: str
    status: ContactStatus
    created_at: datetime


class AdminContactDetail(_OrmBase):
    id: int
    user_id: int | None
    name: str
    email: str
    title: str
    content: str
    status: ContactStatus
    answered_at: datetime | None
    answer_content: str | None
    created_at: datetime


class AdminContactListResponse(BaseModel):
    items: list[AdminContactListItem]
    meta: PageMeta


class AdminContactStatusUpdate(BaseModel):
    status: ContactStatus


class AdminContactAnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=3000)
