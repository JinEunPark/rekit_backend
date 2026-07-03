"""help 모듈 Repository — notices / faqs / contacts 테이블 접근."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.help.models import Contact, ContactStatus, Faq, Notice


class HelpRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── 공지사항 ─────────────────────────────────────────────────────

    async def get_notice_list(
        self, page: int, size: int, *, published_only: bool = True
    ) -> tuple[list[Notice], int]:
        base = select(Notice)
        if published_only:
            base = base.where(Notice.is_published.is_(True))

        count_stmt = select(func.count()).select_from(base.subquery())
        total: int = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            base
            .order_by(Notice.is_pinned.desc(), Notice.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars()), total

    async def get_notice(self, notice_id: int) -> Notice | None:
        stmt = select(Notice).where(Notice.id == notice_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def save_notice(self, notice: Notice) -> Notice:
        self._session.add(notice)
        await self._session.flush()
        return notice

    async def delete_notice(self, notice: Notice) -> None:
        await self._session.delete(notice)

    # ── FAQ ──────────────────────────────────────────────────────────

    async def get_faq_list(
        self, page: int, size: int, *, category: str | None = None, published_only: bool = True
    ) -> tuple[list[Faq], int]:
        base = select(Faq)
        if published_only:
            base = base.where(Faq.is_published.is_(True))
        if category:
            base = base.where(Faq.category == category)

        count_stmt = select(func.count()).select_from(base.subquery())
        total: int = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            base
            .order_by(Faq.category, Faq.sort_order, Faq.id)
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars()), total

    async def get_all_faqs(self, *, category: str | None = None) -> list[Faq]:
        """published FAQ 전체 단일 SELECT — 공개 목록용 (COUNT/페이지네이션 없음)."""
        stmt = select(Faq).where(Faq.is_published.is_(True))
        if category:
            stmt = stmt.where(Faq.category == category)
        stmt = stmt.order_by(Faq.category, Faq.sort_order, Faq.id)
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def get_faq(self, faq_id: int) -> Faq | None:
        stmt = select(Faq).where(Faq.id == faq_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def save_faq(self, faq: Faq) -> Faq:
        self._session.add(faq)
        await self._session.flush()
        return faq

    async def delete_faq(self, faq: Faq) -> None:
        await self._session.delete(faq)

    # ── 문의하기 ─────────────────────────────────────────────────────

    async def get_contact_list(
        self, page: int, size: int, *, status: ContactStatus | None = None
    ) -> tuple[list[Contact], int]:
        base = select(Contact)
        if status:
            base = base.where(Contact.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total: int = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            base
            .order_by(Contact.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars()), total

    async def get_contact(self, contact_id: int) -> Contact | None:
        stmt = select(Contact).where(Contact.id == contact_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def save_contact(self, contact: Contact) -> Contact:
        self._session.add(contact)
        await self._session.flush()
        return contact
