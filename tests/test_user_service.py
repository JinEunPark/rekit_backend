"""UserService 도메인 로직 검증 — DB 없이.

change_password:
- 정상: password_hash 갱신 + must_change_password=False
- 현재 비번 불일치: InvalidCredentials raise
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.exceptions import InvalidCredentials
from app.core.security import hash_password, verify_password
from app.user.models import User, UserRole
from app.user.user_service import UserService


def _make_user(
    *,
    plain_password: str = "abc12345",
    must_change: bool = False,
) -> User:
    now = datetime.now(UTC)
    return User(
        id=1,
        login_id="testuser",
        email="test@example.com",
        password_hash=hash_password(plain_password),
        username="테스트",
        role=UserRole.USER,
        is_active=True,
        must_change_password=must_change,
        agreed_terms_at=now,
        agreed_privacy_at=now,
    )


def test_change_password_replaces_hash_and_clears_must_change_flag() -> None:
    # Arrange
    user = _make_user(plain_password="old12345", must_change=True)
    service = UserService()

    # Act
    service.change_password(user=user, current_password="old12345", new_password="new99zzz")

    # Assert
    assert verify_password("new99zzz", user.password_hash)
    assert not verify_password("old12345", user.password_hash)
    assert user.must_change_password is False


def test_change_password_raises_when_current_password_mismatch() -> None:
    # Arrange
    user = _make_user(plain_password="actualpw1")
    service = UserService()

    # Act / Assert
    with pytest.raises(InvalidCredentials):
        service.change_password(
            user=user, current_password="wrongpw1", new_password="new99zzz"
        )

    # password_hash 는 그대로
    assert verify_password("actualpw1", user.password_hash)


def test_change_password_does_not_match_new_password_against_old_hash() -> None:
    """edge — 새 비번이 우연히 옛 비번과 같아도 정상 동작 (그냥 새로 hash)."""
    # Arrange
    user = _make_user(plain_password="same1234")
    service = UserService()

    # Act
    service.change_password(user=user, current_password="same1234", new_password="same1234")

    # Assert — bcrypt salt 가 매번 다르므로 hash 자체는 바뀜
    assert verify_password("same1234", user.password_hash)
