"""get_current_user 인증 dependency 단위 테스트.

JWT access 토큰 → User 객체 변환 흐름. FastAPI Depends 와 무관하게
함수를 직접 호출해서 검증한다 (Depends 는 기본값일 뿐 — 명시 인자 우선).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.auth.auth_repository import AuthRepository
from app.core.deps import get_current_user
from app.core.exceptions import AccountInactive, TokenExpired
from app.core.security import create_access_token
from app.user.models import User, UserRole


def _make_user(*, user_id: int = 1, is_active: bool = True) -> User:
    """테스트용 User 인스턴스. DB 저장은 안 하므로 server_default 컬럼은 임의값."""
    now = datetime.now(UTC)
    return User(
        id=user_id,
        login_id="testuser",
        email="test@example.com",
        password_hash="$2b$12$dummy",
        username="테스트",
        role=UserRole.USER,
        is_active=is_active,
        agreed_terms_at=now,
        agreed_privacy_at=now,
    )


class _FakeRepo:
    """AuthRepository 의 fake — get_by_id 만 구현. 다른 dependency 와 시그니처 호환."""

    def __init__(self, users_by_id: dict[int, User]) -> None:
        self._by_id = users_by_id

    async def get_by_id(self, user_id: int) -> User | None:
        return self._by_id.get(user_id)


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.mark.asyncio
async def test_get_current_user_returns_user_for_valid_access_token() -> None:
    # Arrange
    user = _make_user(user_id=42)
    repo = _FakeRepo({42: user})
    token = create_access_token(sub="42", claims={"role": "USER"})

    # Act
    result = await get_current_user(credentials=_bearer(token), repo=repo)  # type: ignore[arg-type]

    # Assert
    assert result is user


@pytest.mark.asyncio
async def test_get_current_user_raises_token_expired_when_user_not_found() -> None:
    """JWT 는 유효한데 sub 가 가리키는 user 가 DB 에 없는 경우 — 토큰 위조 또는 사용자 삭제."""
    # Arrange
    repo = _FakeRepo({})
    token = create_access_token(sub="99", claims={"role": "USER"})

    # Act / Assert
    with pytest.raises(TokenExpired):
        await get_current_user(credentials=_bearer(token), repo=repo)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_current_user_raises_account_inactive_for_disabled_user() -> None:
    """비활성 계정(탈퇴/정지) 은 403 ACCOUNT_INACTIVE."""
    # Arrange
    user = _make_user(user_id=7, is_active=False)
    repo = _FakeRepo({7: user})
    token = create_access_token(sub="7", claims={"role": "USER"})

    # Act / Assert
    with pytest.raises(AccountInactive):
        await get_current_user(credentials=_bearer(token), repo=repo)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_current_user_rejects_refresh_token() -> None:
    """type='refresh' 토큰을 access 자리에 쓰면 거부 (decode_token 의 가드 재사용)."""
    # Arrange
    from app.core.security import create_refresh_token

    user = _make_user(user_id=1)
    repo = _FakeRepo({1: user})
    refresh = create_refresh_token(sub="1")

    # Act / Assert
    with pytest.raises(TokenExpired):
        await get_current_user(credentials=_bearer(refresh), repo=repo)  # type: ignore[arg-type]


def test_account_inactive_is_403_with_proper_code() -> None:
    """예외 클래스 자체 검증."""
    from fastapi import status

    exc = AccountInactive()
    assert exc.code == "ACCOUNT_INACTIVE"
    assert exc.http_status == status.HTTP_403_FORBIDDEN
    assert isinstance(exc.message, str) and exc.message
