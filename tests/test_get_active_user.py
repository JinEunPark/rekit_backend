"""get_active_user 인증 가드 단위 테스트.

get_current_user 결과 + must_change_password=False 검증.
- True 면 PasswordChangeRequired (403, 임시 비번 발급 직후 사용자)
- False 면 user 그대로 반환

비번 변경 endpoint (POST /users/me/password) 만 get_current_user 를 직접 사용.
다른 모든 보호 endpoint 는 get_active_user 를 사용해 임시 비번 사용자를 차단한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.deps import get_active_user
from app.core.exceptions import PasswordChangeRequired
from app.user.models import User, UserRole


def _make_user(*, must_change: bool = False) -> User:
    now = datetime.now(UTC)
    return User(
        id=1,
        login_id="testuser",
        email="test@example.com",
        password_hash="$2b$12$dummy",
        username="테스트",
        role=UserRole.USER,
        is_active=True,
        must_change_password=must_change,
        agreed_terms_at=now,
        agreed_privacy_at=now,
    )


@pytest.mark.asyncio
async def test_get_active_user_returns_user_when_password_change_not_required() -> None:
    # Arrange
    user = _make_user(must_change=False)

    # Act
    result = await get_active_user(user=user)

    # Assert
    assert result is user


@pytest.mark.asyncio
async def test_get_active_user_raises_when_must_change_password_true() -> None:
    """임시 비번 발급 직후 사용자 — 비번 변경 외 endpoint 차단."""
    # Arrange
    user = _make_user(must_change=True)

    # Act / Assert
    with pytest.raises(PasswordChangeRequired):
        await get_active_user(user=user)


def test_password_change_required_is_403_with_proper_code() -> None:
    """예외 클래스 메타 검증."""
    from fastapi import status

    exc = PasswordChangeRequired()
    assert exc.code == "PASSWORD_CHANGE_REQUIRED"
    assert exc.http_status == status.HTTP_403_FORBIDDEN
    assert isinstance(exc.message, str) and exc.message
