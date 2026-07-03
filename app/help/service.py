"""help 모듈 서비스 — 공지사항, FAQ, 문의하기 비즈니스 로직."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.common.email.ports import EmailSender
from app.common.email.templates import render_contact_confirm_email, render_contact_notify_email
from app.core.config import settings
from app.core.exceptions import ContactNotFoundError, FaqNotFoundError, NoticeNotFoundError
from app.core.pagination import build_page_meta
from app.help.models import Contact, ContactStatus, Faq, Notice
from app.help.repository import HelpRepository
from app.help.schemas import (
    AdminContactDetail,
    AdminContactListItem,
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
    ContactRequest,
    FaqItem,
    FaqListResponse,
    NoticeDetail,
    NoticeListItem,
    NoticeListResponse,
)


class HelpService:
    """공개 help API 서비스 — 공지사항 조회, FAQ 조회, 문의 접수."""

    def __init__(self, repo: HelpRepository, email_sender: EmailSender) -> None:
        self._repo = repo
        self._email_sender = email_sender

    # ── 공지사항 ─────────────────────────────────────────────────────

    async def list_notices(self, page: int, size: int) -> NoticeListResponse:
        notices, total = await self._repo.get_notice_list(page, size, published_only=True)
        return NoticeListResponse(
            items=[NoticeListItem.model_validate(n) for n in notices],
            meta=build_page_meta(total, page, size),
        )

    async def get_notice(self, notice_id: int) -> NoticeDetail:
        notice = await self._repo.get_notice(notice_id)
        if notice is None or not notice.is_published:
            raise NoticeNotFoundError()
        return NoticeDetail.model_validate(notice)

    # ── FAQ ──────────────────────────────────────────────────────────

    async def list_faqs(self, category: str | None = None) -> FaqListResponse:
        """published FAQ를 단일 SELECT로 반환. COUNT/페이지네이션 없음."""
        faqs = await self._repo.get_all_faqs(category=category)
        return FaqListResponse(items=[FaqItem.model_validate(f) for f in faqs])

    # ── 문의하기 ─────────────────────────────────────────────────────

    async def submit_contact(
        self, req: ContactRequest, *, user_id: int | None = None
    ) -> None:
        contact = Contact(
            user_id=user_id,
            name=req.name,
            email=req.email,
            phone=req.phone,
            title=req.title,
            content=req.content,
            status=ContactStatus.PENDING,
        )
        await self._repo.save_contact(contact)

        tasks = [
            self._email_sender.send(
                to=req.email,
                subject="[rekit] 문의가 접수되었습니다",
                body=(
                    f"안녕하세요 {req.name}님, 문의가 접수되었습니다. "
                    "영업일 기준 1~2일 내 답변드리겠습니다."
                ),
                html_body=render_contact_confirm_email(name=req.name, title=req.title),
            )
        ]
        admin_email = settings.effective_admin_email
        if admin_email:
            tasks.append(
                self._email_sender.send(
                    to=admin_email,
                    subject=f"[rekit 문의] {req.title}",
                    body=(
                        f"문의자: {req.name} ({req.email})\n"
                        f"제목: {req.title}\n내용: {req.content}"
                    ),
                    html_body=render_contact_notify_email(
                        name=req.name,
                        email=req.email,
                        phone=req.phone,
                        title=req.title,
                        content=req.content,
                    ),
                )
            )
        await asyncio.gather(*tasks)


class AdminHelpService:
    """어드민 help API 서비스 — 공지사항/FAQ CRUD, 문의 관리."""

    def __init__(self, repo: HelpRepository) -> None:
        self._repo = repo

    # ── 공지사항 ─────────────────────────────────────────────────────

    async def list_notices(self, page: int, size: int) -> AdminNoticeListResponse:
        notices, total = await self._repo.get_notice_list(page, size, published_only=False)
        return AdminNoticeListResponse(
            items=[AdminNoticeResponse.model_validate(n) for n in notices],
            meta=build_page_meta(total, page, size),
        )

    async def create_notice(self, body: AdminNoticeCreate) -> AdminNoticeResponse:
        notice = Notice(
            title=body.title,
            content=body.content,
            is_pinned=body.is_pinned,
            is_published=body.is_published,
        )
        await self._repo.save_notice(notice)
        return AdminNoticeResponse.model_validate(notice)

    async def update_notice(self, notice_id: int, body: AdminNoticeUpdate) -> AdminNoticeResponse:
        notice = await self._repo.get_notice(notice_id)
        if notice is None:
            raise NoticeNotFoundError()
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(notice, k, v)
        await self._repo.save_notice(notice)
        return AdminNoticeResponse.model_validate(notice)

    async def delete_notice(self, notice_id: int) -> None:
        notice = await self._repo.get_notice(notice_id)
        if notice is None:
            raise NoticeNotFoundError()
        await self._repo.delete_notice(notice)

    # ── FAQ ──────────────────────────────────────────────────────────

    async def list_faqs(self, page: int, size: int, category: str | None) -> AdminFaqListResponse:
        faqs, total = await self._repo.get_faq_list(
            page, size, category=category, published_only=False
        )
        return AdminFaqListResponse(
            items=[AdminFaqResponse.model_validate(f) for f in faqs],
            meta=build_page_meta(total, page, size),
        )

    async def create_faq(self, body: AdminFaqCreate) -> AdminFaqResponse:
        faq = Faq(
            category=body.category,
            question=body.question,
            answer=body.answer,
            sort_order=body.sort_order,
            is_published=body.is_published,
        )
        await self._repo.save_faq(faq)
        return AdminFaqResponse.model_validate(faq)

    async def update_faq(self, faq_id: int, body: AdminFaqUpdate) -> AdminFaqResponse:
        faq = await self._repo.get_faq(faq_id)
        if faq is None:
            raise FaqNotFoundError()
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(faq, k, v)
        await self._repo.save_faq(faq)
        return AdminFaqResponse.model_validate(faq)

    async def delete_faq(self, faq_id: int) -> None:
        faq = await self._repo.get_faq(faq_id)
        if faq is None:
            raise FaqNotFoundError()
        await self._repo.delete_faq(faq)

    # ── 문의 관리 ────────────────────────────────────────────────────

    async def list_contacts(
        self, page: int, size: int, status: ContactStatus | None
    ) -> AdminContactListResponse:
        contacts, total = await self._repo.get_contact_list(page, size, status=status)
        return AdminContactListResponse(
            items=[AdminContactListItem.model_validate(c) for c in contacts],
            meta=build_page_meta(total, page, size),
        )

    async def get_contact(self, contact_id: int) -> AdminContactDetail:
        contact = await self._repo.get_contact(contact_id)
        if contact is None:
            raise ContactNotFoundError()
        return AdminContactDetail.model_validate(contact)

    async def update_contact_status(
        self, contact_id: int, body: AdminContactStatusUpdate
    ) -> AdminContactDetail:
        contact = await self._repo.get_contact(contact_id)
        if contact is None:
            raise ContactNotFoundError()
        contact.status = body.status
        if body.status == ContactStatus.ANSWERED:
            contact.answered_at = datetime.now(UTC)
        else:
            contact.answered_at = None
        return AdminContactDetail.model_validate(contact)
