"""help 모듈 단위 테스트 — HelpService / AdminHelpService.

DB/Redis 없이 fake repo + fake email sender 로 검증한다.
AAA 패턴: Arrange / Act / Assert.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.exceptions import ContactNotFoundError, FaqNotFoundError, NoticeNotFoundError
from app.help.models import Contact, ContactStatus, Faq, Notice
from app.help.schemas import (
    AdminContactAnswerRequest,
    AdminContactStatusUpdate,
    AdminFaqCreate,
    AdminFaqUpdate,
    AdminNoticeCreate,
    AdminNoticeUpdate,
    ContactRequest,
)
from app.help.service import AdminHelpService, HelpService

# ── Fake 인프라 ────────────────────────────────────────────────────────

class _FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []  # (to, subject)

    async def send(self, *, to: str, subject: str, body: str, html_body: str | None = None) -> None:
        self.sent.append((to, subject))


class _FakeHelpRepo:
    def __init__(self) -> None:
        self._notices: dict[int, Notice] = {}
        self._faqs: dict[int, Faq] = {}
        self._contacts: dict[int, Contact] = {}
        self._next_id = 1

    def _new_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    # Notice
    async def get_notice_list(self, page, size, *, published_only=True):
        items = [n for n in self._notices.values() if not published_only or n.is_published]
        # 실제 DB 쿼리와 동일한 정렬: pinned DESC, created_at DESC
        items.sort(key=lambda n: (not n.is_pinned, -(n.created_at.timestamp())))
        total = len(items)
        start = (page - 1) * size
        return items[start: start + size], total

    async def get_notice(self, notice_id):
        return self._notices.get(notice_id)

    async def save_notice(self, notice):
        if notice.id is None:
            notice.id = self._new_id()
            now = datetime.now(UTC)
            notice.created_at = now
            notice.updated_at = now
        self._notices[notice.id] = notice
        return notice

    async def delete_notice(self, notice):
        self._notices.pop(notice.id, None)

    # Faq
    async def get_faq_list(self, page, size, *, category=None, published_only=True):
        items = [
            f for f in self._faqs.values()
            if (not published_only or f.is_published)
            and (category is None or f.category == category)
        ]
        items.sort(key=lambda f: (f.category, f.sort_order, f.id))
        total = len(items)
        start = (page - 1) * size
        return items[start: start + size], total

    async def get_all_faqs(self, *, category=None):
        items = [f for f in self._faqs.values() if f.is_published]
        if category:
            items = [f for f in items if f.category == category]
        items.sort(key=lambda f: (f.category, f.sort_order, f.id))
        return items

    async def get_faq(self, faq_id):
        return self._faqs.get(faq_id)

    async def save_faq(self, faq):
        if faq.id is None:
            faq.id = self._new_id()
            now = datetime.now(UTC)
            faq.created_at = now
            faq.updated_at = now
        self._faqs[faq.id] = faq
        return faq

    async def delete_faq(self, faq):
        self._faqs.pop(faq.id, None)

    # Contact
    async def get_contact_list(self, page, size, *, status=None, user_id=None):
        items = [
            c for c in self._contacts.values()
            if (status is None or c.status == status)
            and (user_id is None or c.user_id == user_id)
        ]
        items.sort(key=lambda c: c.id, reverse=True)
        total = len(items)
        start = (page - 1) * size
        return items[start: start + size], total

    async def get_contact(self, contact_id):
        return self._contacts.get(contact_id)

    async def get_contact_for_user(self, contact_id, user_id):
        contact = self._contacts.get(contact_id)
        if contact is None or contact.user_id != user_id:
            return None
        return contact

    async def save_contact(self, contact):
        if contact.id is None:
            contact.id = self._new_id()
            now = datetime.now(UTC)
            contact.created_at = now
            contact.updated_at = now
        self._contacts[contact.id] = contact
        return contact


# ── 모듈 레벨 팩토리 ─────────────────────────────────────────────────

def _make_help_service() -> tuple[HelpService, _FakeHelpRepo, _FakeEmailSender]:
    repo = _FakeHelpRepo()
    email = _FakeEmailSender()
    return HelpService(repo, email), repo, email  # type: ignore[arg-type]


def _make_admin_service() -> tuple[AdminHelpService, _FakeHelpRepo, _FakeEmailSender]:
    repo = _FakeHelpRepo()
    email = _FakeEmailSender()
    return AdminHelpService(repo, email), repo, email  # type: ignore[arg-type]


# ── 픽스처 헬퍼 ──────────────────────────────────────────────────────

def _make_notice(*, title="공지", content="내용", is_pinned=False, is_published=True) -> Notice:
    n = Notice()
    n.id = None  # type: ignore[assignment]
    n.title = title
    n.content = content
    n.is_pinned = is_pinned
    n.is_published = is_published
    return n


def _make_faq(
    *, category="주문", question="Q?", answer="A.", sort_order=0, is_published=True
) -> Faq:
    f = Faq()
    f.id = None  # type: ignore[assignment]
    f.category = category
    f.question = question
    f.answer = answer
    f.sort_order = sort_order
    f.is_published = is_published
    return f


# ── HelpService 테스트 ────────────────────────────────────────────────

class TestHelpServiceNotice:
    @pytest.mark.asyncio
    async def test_list_notices_published_only(self):
        """비게시 공지는 목록에서 제외된다."""
        service, repo, _ = _make_help_service()
        await repo.save_notice(_make_notice(title="공개", is_published=True))
        await repo.save_notice(_make_notice(title="비공개", is_published=False))

        result = await service.list_notices(1, 20)

        assert len(result.items) == 1
        assert result.items[0].title == "공개"

    @pytest.mark.asyncio
    async def test_list_notices_pinned_first(self):
        """is_pinned=True 항목이 목록 앞에 온다."""
        service, repo, _ = _make_help_service()
        await repo.save_notice(_make_notice(title="일반", is_pinned=False))
        await repo.save_notice(_make_notice(title="고정", is_pinned=True))

        result = await service.list_notices(1, 20)

        assert result.items[0].title == "고정"

    @pytest.mark.asyncio
    async def test_get_notice_not_found(self):
        """존재하지 않는 ID 조회 시 NoticeNotFoundError."""
        service, _, __ = _make_help_service()

        with pytest.raises(NoticeNotFoundError):
            await service.get_notice(999)

    @pytest.mark.asyncio
    async def test_get_notice_unpublished_raises(self):
        """비게시 공지 단건 조회 시 NoticeNotFoundError (공개 API 보호)."""
        service, repo, _ = _make_help_service()
        notice = _make_notice(is_published=False)
        await repo.save_notice(notice)

        with pytest.raises(NoticeNotFoundError):
            await service.get_notice(notice.id)


class TestHelpServiceFaq:
    @pytest.mark.asyncio
    async def test_list_faqs_all(self):
        """카테고리 필터 없이 전체 FAQ 반환."""
        service, repo, _ = _make_help_service()
        await repo.save_faq(_make_faq(category="주문"))
        await repo.save_faq(_make_faq(category="배송"))

        result = await service.list_faqs()

        assert len(result.items) == 2

    @pytest.mark.asyncio
    async def test_list_faqs_category_filter(self):
        """category 필터 적용 시 해당 카테고리만 반환."""
        service, repo, _ = _make_help_service()
        await repo.save_faq(_make_faq(category="주문"))
        await repo.save_faq(_make_faq(category="배송"))

        result = await service.list_faqs(category="주문")

        assert len(result.items) == 1
        assert result.items[0].category == "주문"

    @pytest.mark.asyncio
    async def test_list_faqs_published_only(self):
        """비게시 FAQ는 공개 목록에서 제외된다."""
        service, repo, _ = _make_help_service()
        await repo.save_faq(_make_faq(is_published=True))
        await repo.save_faq(_make_faq(is_published=False))

        result = await service.list_faqs()

        assert len(result.items) == 1


class TestHelpServiceContact:
    @pytest.mark.asyncio
    async def test_submit_contact_saves_to_db(self):
        """문의 접수 시 Contact 레코드가 저장되고 로그인 사용자 정보가 채워진다."""
        service, repo, _ = _make_help_service()
        req = ContactRequest(title="문의합니다", content="자세한 내용입니다.")

        await service.submit_contact(
            req, user_id=1, name="홍길동", email="hong@example.com"
        )

        assert len(repo._contacts) == 1
        saved = next(iter(repo._contacts.values()))
        assert saved.name == "홍길동"
        assert saved.email == "hong@example.com"
        assert saved.user_id == 1
        assert saved.status == ContactStatus.PENDING

    @pytest.mark.asyncio
    async def test_submit_contact_sends_confirm_email(self):
        """문의 접수 시 로그인 사용자 이메일로 접수 확인 이메일이 발송된다."""
        service, _, email_sender = _make_help_service()
        req = ContactRequest(title="문의제목", content="문의 내용을 상세히 입력합니다.")

        await service.submit_contact(
            req, user_id=1, name="홍길동", email="hong@example.com"
        )

        confirm_mails = [m for m in email_sender.sent if m[0] == "hong@example.com"]
        assert len(confirm_mails) == 1
        assert "접수" in confirm_mails[0][1]

    @pytest.mark.asyncio
    async def test_submit_contact_status_is_pending(self):
        """신규 문의 상태는 PENDING이다."""
        service, repo, _ = _make_help_service()
        req = ContactRequest(title="상태 확인", content="초기 상태 확인용 문의입니다.")

        await service.submit_contact(
            req, user_id=1, name="테스터", email="test@example.com"
        )

        saved = next(iter(repo._contacts.values()))
        assert saved.status == ContactStatus.PENDING

    @pytest.mark.asyncio
    async def test_list_my_contacts_only_returns_own(self):
        """본인 문의만 목록에 포함된다."""
        service, _, __ = _make_help_service()
        await service.submit_contact(
            ContactRequest(title="내 문의1", content="내용을 채워봅니다."),
            user_id=1, name="A", email="a@example.com",
        )
        await service.submit_contact(
            ContactRequest(title="내 문의2", content="내용을 채워봅니다."),
            user_id=1, name="A", email="a@example.com",
        )
        await service.submit_contact(
            ContactRequest(title="다른 사람 문의", content="내용을 채워봅니다."),
            user_id=2, name="B", email="b@example.com",
        )

        result = await service.list_my_contacts(1, 1, 20)

        assert result.meta.total == 2
        assert all(c.title != "다른 사람 문의" for c in result.items)

    @pytest.mark.asyncio
    async def test_get_my_contact_returns_detail(self):
        """본인 문의 상세를 조회한다."""
        service, repo, _ = _make_help_service()
        await service.submit_contact(
            ContactRequest(title="상세 조회용", content="상세 조회 테스트 내용."),
            user_id=1, name="A", email="a@example.com",
        )
        contact = next(iter(repo._contacts.values()))

        result = await service.get_my_contact(1, contact.id)

        assert result.title == "상세 조회용"

    @pytest.mark.asyncio
    async def test_get_my_contact_of_other_user_raises_not_found(self):
        """다른 사용자의 문의는 ContactNotFoundError로 응답한다 (존재 여부 비노출)."""
        service, repo, _ = _make_help_service()
        await service.submit_contact(
            ContactRequest(title="B의 문의", content="B가 작성한 문의 내용."),
            user_id=2, name="B", email="b@example.com",
        )
        contact = next(iter(repo._contacts.values()))

        with pytest.raises(ContactNotFoundError):
            await service.get_my_contact(1, contact.id)

    @pytest.mark.asyncio
    async def test_get_my_contact_not_found(self):
        """존재하지 않는 문의 ID 조회 시 ContactNotFoundError."""
        service, _, __ = _make_help_service()

        with pytest.raises(ContactNotFoundError):
            await service.get_my_contact(1, 999)


# ── AdminHelpService 테스트 ──────────────────────────────────────────

class TestAdminHelpServiceNotice:
    @pytest.mark.asyncio
    async def test_create_notice(self):
        """공지사항 생성 후 ID가 부여된다."""
        service, _, __ = _make_admin_service()
        body = AdminNoticeCreate(
            title="새 공지", content="내용", is_pinned=False, is_published=True
        )

        result = await service.create_notice(body)

        assert result.id is not None
        assert result.title == "새 공지"

    @pytest.mark.asyncio
    async def test_update_notice_partial(self):
        """PATCH는 전달된 필드만 변경한다."""
        service, repo, _ = _make_admin_service()
        notice = _make_notice(title="원본", is_pinned=False)
        await repo.save_notice(notice)

        result = await service.update_notice(notice.id, AdminNoticeUpdate(is_pinned=True))

        assert result.title == "원본"
        assert result.is_pinned is True

    @pytest.mark.asyncio
    async def test_update_notice_not_found(self):
        """존재하지 않는 공지 수정 시 NoticeNotFoundError."""
        service, _, __ = _make_admin_service()

        with pytest.raises(NoticeNotFoundError):
            await service.update_notice(999, AdminNoticeUpdate(title="수정"))

    @pytest.mark.asyncio
    async def test_delete_notice(self):
        """삭제 후 repo에서 제거된다."""
        service, repo, _ = _make_admin_service()
        notice = _make_notice()
        await repo.save_notice(notice)

        await service.delete_notice(notice.id)

        assert notice.id not in repo._notices

    @pytest.mark.asyncio
    async def test_delete_notice_not_found(self):
        """존재하지 않는 공지 삭제 시 NoticeNotFoundError."""
        service, _, __ = _make_admin_service()

        with pytest.raises(NoticeNotFoundError):
            await service.delete_notice(999)

    @pytest.mark.asyncio
    async def test_list_notices_includes_unpublished(self):
        """어드민 목록은 비게시 포함 전체 반환."""
        service, repo, _ = _make_admin_service()
        await repo.save_notice(_make_notice(is_published=True))
        await repo.save_notice(_make_notice(is_published=False))

        result = await service.list_notices(1, 20)

        assert result.meta.total == 2


class TestAdminHelpServiceFaq:
    @pytest.mark.asyncio
    async def test_create_faq(self):
        """FAQ 생성."""
        service, _, __ = _make_admin_service()
        body = AdminFaqCreate(category="결제", question="Q?", answer="A.", sort_order=1)

        result = await service.create_faq(body)

        assert result.id is not None
        assert result.category == "결제"

    @pytest.mark.asyncio
    async def test_update_faq_not_found(self):
        """존재하지 않는 FAQ 수정 시 FaqNotFoundError."""
        service, _, __ = _make_admin_service()

        with pytest.raises(FaqNotFoundError):
            await service.update_faq(999, AdminFaqUpdate(question="변경"))

    @pytest.mark.asyncio
    async def test_delete_faq(self):
        """FAQ 삭제 후 repo에서 제거된다."""
        service, repo, _ = _make_admin_service()
        faq = _make_faq()
        await repo.save_faq(faq)

        await service.delete_faq(faq.id)

        assert faq.id not in repo._faqs


class TestAdminHelpServiceContact:
    def _make_contact(self) -> Contact:
        c = Contact()
        c.id = None  # type: ignore[assignment]
        c.user_id = None
        c.name = "홍길동"
        c.email = "hong@example.com"
        c.title = "문의"
        c.content = "내용"
        c.status = ContactStatus.PENDING
        c.answered_at = None
        c.answer_content = None
        return c

    @pytest.mark.asyncio
    async def test_get_contact_not_found(self):
        """존재하지 않는 문의 조회 시 ContactNotFoundError."""
        service, _, __ = _make_admin_service()

        with pytest.raises(ContactNotFoundError):
            await service.get_contact(999)

    @pytest.mark.asyncio
    async def test_update_status_to_answered(self):
        """ANSWERED로 변경 시 answered_at이 채워진다."""
        service, repo, _ = _make_admin_service()
        contact = self._make_contact()
        await repo.save_contact(contact)

        result = await service.update_contact_status(
            contact.id, AdminContactStatusUpdate(status=ContactStatus.ANSWERED)
        )

        assert result.status == ContactStatus.ANSWERED
        assert result.answered_at is not None

    @pytest.mark.asyncio
    async def test_update_status_to_pending_clears_answered_at(self):
        """PENDING으로 되돌리면 answered_at이 None으로 초기화된다."""
        service, repo, _ = _make_admin_service()
        contact = self._make_contact()
        contact.answered_at = datetime.now(UTC)
        contact.status = ContactStatus.ANSWERED
        await repo.save_contact(contact)

        result = await service.update_contact_status(
            contact.id, AdminContactStatusUpdate(status=ContactStatus.PENDING)
        )

        assert result.answered_at is None

    @pytest.mark.asyncio
    async def test_list_contacts_status_filter(self):
        """status 필터 적용 시 해당 상태 문의만 반환."""
        service, repo, _ = _make_admin_service()
        pending = self._make_contact()
        answered = self._make_contact()
        answered.status = ContactStatus.ANSWERED
        await repo.save_contact(pending)
        await repo.save_contact(answered)

        result = await service.list_contacts(1, 20, ContactStatus.PENDING)

        assert result.meta.total == 1
        assert result.items[0].status == ContactStatus.PENDING

    @pytest.mark.asyncio
    async def test_answer_contact_saves_content_and_marks_answered(self):
        """답변 등록 시 answer_content 저장, status ANSWERED, answered_at 채워진다."""
        service, repo, _ = _make_admin_service()
        contact = self._make_contact()
        await repo.save_contact(contact)

        result = await service.answer_contact(
            contact.id, AdminContactAnswerRequest(answer="답변 내용입니다.")
        )

        assert result.answer_content == "답변 내용입니다."
        assert result.status == ContactStatus.ANSWERED
        assert result.answered_at is not None

    @pytest.mark.asyncio
    async def test_answer_contact_sends_email_to_customer(self):
        """답변 등록 시 문의자 이메일로 답변 완료 메일이 발송된다."""
        service, repo, email_sender = _make_admin_service()
        contact = self._make_contact()
        await repo.save_contact(contact)

        await service.answer_contact(
            contact.id, AdminContactAnswerRequest(answer="답변 내용입니다.")
        )

        answer_mails = [m for m in email_sender.sent if m[0] == "hong@example.com"]
        assert len(answer_mails) == 1
        assert "답변" in answer_mails[0][1]

    @pytest.mark.asyncio
    async def test_answer_contact_not_found(self):
        """존재하지 않는 문의에 답변 시 ContactNotFoundError."""
        service, _, __ = _make_admin_service()

        with pytest.raises(ContactNotFoundError):
            await service.answer_contact(999, AdminContactAnswerRequest(answer="답변"))
