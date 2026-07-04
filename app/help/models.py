"""help 모듈 모델 — 공지사항(Notice), FAQ, 문의하기(Contact)."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Identity, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.user.models import User


class ContactStatus(enum.StrEnum):
    PENDING = "PENDING"
    ANSWERED = "ANSWERED"


class Notice(Base, TimestampMixin):
    """공지사항. is_pinned=True 인 항목은 목록 최상단에 노출."""

    __tablename__ = "notices"

    id: Mapped[int] = mapped_column(Identity(always=False), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="상단 고정 여부"
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="게시 여부 (False=비공개)"
    )


class Faq(Base, TimestampMixin):
    """자주 묻는 질문. category 로 그룹화, sort_order 로 정렬."""

    __tablename__ = "faqs"

    id: Mapped[int] = mapped_column(Identity(always=False), primary_key=True)
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="카테고리 (예: 주문, 배송, 결제, 회원, 기타)",
    )
    question: Mapped[str] = mapped_column(String(300), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="카테고리 내 노출 순서 (오름차순)"
    )
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Contact(Base, TimestampMixin):
    """1:1 문의. 로그인 회원만 접수 가능 — user_id/name/email 은 회원 프로필 기준으로 채워진다."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Identity(always=False), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="문의 회원 FK — 탈퇴 시 SET NULL",
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False, comment="답변 수신 이메일")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ContactStatus] = mapped_column(
        Enum(ContactStatus, name="contact_status"),
        default=ContactStatus.PENDING,
        nullable=False,
    )
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="답변 완료 시각"
    )
    answer_content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="관리자 답변 내용"
    )

    user: Mapped[User | None] = relationship("User", lazy="noload")
