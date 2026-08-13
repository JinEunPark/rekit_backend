"""admin_members_repository 통합 테스트 — 실제 Postgres 대상.

전화번호가 010-0000-0000 형식(하이픈 포함)으로 저장되므로, 관리자가 하이픈
없이 검색해도 매칭돼야 한다 — ilike 만으로는 검증 불가(하이픈 유무에 따라
DB 컬럼 값과 불일치)해 실제 SQL 결과로 확인한다.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.user.admin_members_repository import AdminMembersRepository
from app.user.admin_members_schemas import AdminMemberListParams
from app.user.models import User


async def _make_user(session: AsyncSession, *, phone_digits: str) -> tuple[User, str]:
    """unique 값을 login_id/email/phone 뒷자리에 공통으로 써서 다른(시드) 데이터와
    검색어가 우연히 겹치지 않게 한다. (phone_digits: 하이픈 없는 8자리)"""
    unique = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    phone = f"010-{phone_digits[:4]}-{phone_digits[4:]}"
    user = User(
        login_id=f"admtest{unique}",
        email=f"admtest{unique}@example.com",
        password_hash=hash_password("pw1234ab"),
        username="관리자검색테스트",
        phone=phone,
        agreed_terms_at=now,
        agreed_privacy_at=now,
    )
    session.add(user)
    await session.flush()
    return user, phone


def _unique_phone_digits() -> str:
    """실서비스 시드 데이터(예: 01012345678)와 겹치지 않는 임의의 8자리 뒷번호."""
    return f"{secrets.randbelow(10**8):08d}"


@pytest.mark.asyncio
async def test_search_by_digit_only_query_matches_hyphenated_phone(
    db_session: AsyncSession,
):
    """저장된 전화번호가 010-XXXX-XXXX 이어도 하이픈 없는 검색어로 찾을 수 있다."""
    phone_digits = _unique_phone_digits()
    user, _phone = await _make_user(db_session, phone_digits=phone_digits)
    repo = AdminMembersRepository(db_session)

    try:
        rows, total = await repo.get_list(
            AdminMemberListParams(q=f"010{phone_digits}", page=1, size=20)
        )

        assert total == 1
        assert rows[0].user.id == user.id
    finally:
        await db_session.execute(delete(User).where(User.id == user.id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_search_by_hyphenated_query_still_matches(db_session: AsyncSession):
    """하이픈 포함 검색어도 그대로 매칭된다."""
    phone_digits = _unique_phone_digits()
    user, phone = await _make_user(db_session, phone_digits=phone_digits)
    repo = AdminMembersRepository(db_session)

    try:
        rows, total = await repo.get_list(AdminMemberListParams(q=phone, page=1, size=20))

        assert total == 1
        assert rows[0].user.id == user.id
    finally:
        await db_session.execute(delete(User).where(User.id == user.id))
        await db_session.commit()
