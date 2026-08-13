"""관리자 회원 관리 Pydantic 스키마."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.pagination import PageMeta
from app.user.models import UserRole, UserStatus


class AdminMemberListParams(BaseModel):
    q: str | None = None
    status: UserStatus | None = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


class AdminMemberSummary(BaseModel):
    total: int
    verified: int
    new_this_week: int
    purchased: int


class AdminMemberItem(BaseModel):
    id: int
    login_id: str
    username: str
    email: str
    phone: str | None
    role: UserRole
    status: UserStatus
    is_active: bool
    verified: bool
    created_at: datetime
    order_count: int
    total_purchased: int


class AdminMemberDetail(AdminMemberItem):
    phone_verified_at: datetime | None
    agreed_marketing_at: datetime | None


class AdminMemberListResponse(BaseModel):
    items: list[AdminMemberItem]
    meta: PageMeta


class AdminMemberStatusUpdate(BaseModel):
    status: UserStatus
