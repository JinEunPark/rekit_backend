"""UserService 도메인 로직 검증 — DB 없이.

change_password:
- 정상: password_hash 갱신 + must_change_password=False
- 현재 비번 불일치: InvalidCredentialsError raise

withdraw:
- 비밀번호 확인 후 PII 전체 익명화 + 소셜 계정 삭제
- 비번 불일치 시 InvalidCredentialsError raise
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.exceptions import InvalidCredentialsError
from app.core.security import hash_password, verify_password
from app.user.models import User, UserRole, UserStatus
from app.user.user_schemas import UpdateProfileRequest
from app.user.user_service import UserService

# ── Fake repo ─────────────────────────────────────────────────────────────────


class _FakeUserRepo:
    def __init__(self) -> None:
        self.deleted_social_accounts_for: list[int] = []

    async def delete_social_accounts(self, user_id: int) -> None:
        self.deleted_social_accounts_for.append(user_id)


def _make_service() -> tuple[UserService, _FakeUserRepo]:
    repo = _FakeUserRepo()
    return UserService(repo), repo  # type: ignore[arg-type]


# ── 팩토리 ────────────────────────────────────────────────────────────────────


def _make_user(
    *,
    plain_password: str = "abc12345",
    must_change: bool = False,
    has_password: bool = True,
) -> User:
    now = datetime.now(UTC)
    u = User(
        login_id="testuser",
        email="test@example.com",
        password_hash=hash_password(plain_password),
        username="테스트",
        role=UserRole.USER,
        is_active=True,
        must_change_password=must_change,
        has_password=has_password,
        agreed_terms_at=now,
        agreed_privacy_at=now,
    )
    u.id = 1
    u.phone = "01012345678"
    return u


def test_change_password_replaces_hash_and_clears_must_change_flag() -> None:
    # Arrange
    user = _make_user(plain_password="old12345", must_change=True)
    service, _ = _make_service()

    # Act
    service.change_password(user=user, current_password="old12345", new_password="new99zzz")

    # Assert
    assert verify_password("new99zzz", user.password_hash)
    assert not verify_password("old12345", user.password_hash)
    assert user.must_change_password is False


def test_change_password_raises_when_current_password_mismatch() -> None:
    # Arrange
    user = _make_user(plain_password="actualpw1")
    service, _ = _make_service()

    # Act / Assert
    with pytest.raises(InvalidCredentialsError):
        service.change_password(
            user=user, current_password="wrongpw1", new_password="new99zzz"
        )

    # password_hash 는 그대로
    assert verify_password("actualpw1", user.password_hash)


# ── update_profile ───────────────────────────────────────────────────────────


def test_update_profile_changes_username() -> None:
    user = _make_user()
    service, _ = _make_service()

    service.update_profile(user=user, data=UpdateProfileRequest(username="새이름"))

    assert user.username == "새이름"


def test_update_profile_changes_phone() -> None:
    user = _make_user()
    service, _ = _make_service()

    service.update_profile(user=user, data=UpdateProfileRequest(phone="01099998888"))

    assert user.phone == "010-9999-8888"


def test_update_profile_none_fields_are_skipped() -> None:
    """None 필드는 기존 값을 건드리지 않는다."""
    user = _make_user()
    original_username = user.username
    service, _ = _make_service()

    service.update_profile(user=user, data=UpdateProfileRequest(phone="01011112222"))

    assert user.username == original_username


# ── withdraw ─────────────────────────────────────────────────────────────────


async def test_withdraw_deactivates_user() -> None:
    user = _make_user(plain_password="abc12345")
    service, _ = _make_service()

    await service.withdraw(user=user, password="abc12345")

    assert user.is_active is False
    assert user.status == UserStatus.WITHDRAWN
    assert user.withdrawn_at is not None


async def test_withdraw_anonymizes_identifying_fields() -> None:
    """탈퇴 시 재가입 가능하도록 email·login_id 를 unique 안전한 값으로 교체."""
    user = _make_user()
    service, _ = _make_service()

    await service.withdraw(user=user, password="abc12345")

    assert user.email == f"withdrawn_{user.id}@deleted"
    assert user.login_id == f"withdrawn_{user.id}"


async def test_withdraw_clears_pii_fields() -> None:
    """탈퇴 시 nullable PII 필드(username·phone) 파기."""
    user = _make_user()
    service, _ = _make_service()

    await service.withdraw(user=user, password="abc12345")

    assert user.username == "(탈퇴한 사용자)"
    assert user.phone is None


async def test_withdraw_invalidates_password() -> None:
    """탈퇴 후 password_hash 를 비워 bcrypt 검증 자체가 불가능하게 만든다."""
    user = _make_user(plain_password="abc12345")
    service, _ = _make_service()

    await service.withdraw(user=user, password="abc12345")

    assert user.password_hash == ""


async def test_withdraw_deletes_social_accounts() -> None:
    """탈퇴 시 소셜 계정(PII 포함) 즉시 삭제."""
    user = _make_user()
    service, repo = _make_service()

    await service.withdraw(user=user, password="abc12345")

    assert user.id in repo.deleted_social_accounts_for


async def test_withdraw_raises_when_password_mismatch() -> None:
    """비밀번호 불일치 시 InvalidCredentialsError — PII 변경 없이 탈퇴 차단."""
    user = _make_user(plain_password="abc12345")
    service, _ = _make_service()

    with pytest.raises(InvalidCredentialsError):
        await service.withdraw(user=user, password="wrongpw1")

    assert user.is_active is True
    assert user.withdrawn_at is None
    assert user.email == "test@example.com"


# ── withdraw: 소셜 전용 계정 (has_password=False) ──────────────────────────────


async def test_withdraw_password_holder_without_password_raises() -> None:
    """has_password=True 인데 password 를 안 보내면 거절 — withdrawal_token 으로 우회 불가."""
    user = _make_user(has_password=True)
    service, _ = _make_service()

    with pytest.raises(InvalidCredentialsError):
        await service.withdraw(user=user, password=None, withdrawal_token="whatever")

    assert user.is_active is True


async def test_withdraw_social_only_without_withdrawal_token_raises() -> None:
    """has_password=False 인데 withdrawal_token 없이 password 만 보내면 거절."""
    user = _make_user(has_password=False)
    service, _ = _make_service()

    with pytest.raises(InvalidCredentialsError):
        await service.withdraw(user=user, password="anything", withdrawal_token=None)

    assert user.is_active is True


async def test_withdraw_social_only_with_valid_withdrawal_token_succeeds() -> None:
    """has_password=False + 본인 앞으로 발급된 withdrawal_token → 비밀번호 없이 탈퇴 성공."""
    from app.core.security import create_withdrawal_token

    user = _make_user(has_password=False)
    service, _ = _make_service()
    token = create_withdrawal_token(user_id=user.id)

    await service.withdraw(user=user, password=None, withdrawal_token=token)

    assert user.is_active is False
    assert user.status == UserStatus.WITHDRAWN


async def test_withdraw_social_only_with_token_for_other_user_raises() -> None:
    """withdrawal_token 의 sub 가 다른 user_id 면 거절 — 토큰 재사용/도용 방지."""
    from app.core.security import create_withdrawal_token

    user = _make_user(has_password=False)
    service, _ = _make_service()
    token_for_someone_else = create_withdrawal_token(user_id=user.id + 999)

    with pytest.raises(InvalidCredentialsError):
        await service.withdraw(user=user, password=None, withdrawal_token=token_for_someone_else)

    assert user.is_active is True


def test_change_password_does_not_match_new_password_against_old_hash() -> None:
    """edge — 새 비번이 우연히 옛 비번과 같아도 정상 동작 (그냥 새로 hash)."""
    # Arrange
    user = _make_user(plain_password="same1234")
    service, _ = _make_service()

    # Act
    service.change_password(user=user, current_password="same1234", new_password="same1234")

    # Assert — bcrypt salt 가 매번 다르므로 hash 자체는 바뀜
    assert verify_password("same1234", user.password_hash)
