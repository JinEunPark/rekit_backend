"""AuthService 단위 테스트 (sign_in / sign_up / refresh_token / is_login_id_available).

DB 없이 fake repository 로 도메인 로직만 검증.
실제 DB 연동 검증(통합 테스트) 은 별도 사이클(tests/integration/) 에서 한다.

원칙 (CLAUDE.md TDD §5):
- fake 는 Protocol 상속 안 해도 OK — service 가 호출하는 메서드만 갖추면 됨 (duck typing).
- 실패 케이스 → 성공 케이스 → 부수 동작 순.
- AAA 패턴: Arrange (준비) / Act (실행) / Assert (검증) 구분.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.auth.auth_service import AuthService
from app.core.exceptions import (
    EmailTaken,
    InvalidCredentials,
    TokenExpired,
    UsernameTaken,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
)
from app.user.models import User, UserRole

# ── 테스트 헬퍼 ────────────────────────────────────────


class _FakeAuthRepo:
    """AuthRepository 의 fake. service 가 호출하는 모든 메서드 구현."""

    def __init__(self, user: User | None = None) -> None:
        self._user = user
        self.added: list[User] = []  # add() 호출 검증용

    async def get_by_login_id(self, login_id: str) -> User | None:
        if self._user is None:
            return None
        return self._user if self._user.login_id == login_id else None

    async def get_by_id(self, user_id: int) -> User | None:
        if self._user is None:
            return None
        return self._user if self._user.id == user_id else None

    async def exists_by_login_id(self, login_id: str) -> bool:
        return self._user is not None and self._user.login_id == login_id

    async def exists_by_email(self, email: str) -> bool:
        return self._user is not None and self._user.email == email

    async def add(self, user: User) -> User:
        # 메모리 fake: PK 만 채워주고 보관
        user.id = (self._user.id + 1) if self._user else 1
        self.added.append(user)
        return user


def _make_user(
    *,
    id_: int = 1,
    login_id: str = "eunyoung_kim",
    username: str = "박은영",
    email: str = "user@example.com",
    password: str = "correct-pw",
    is_active: bool = True,
) -> User:
    """테스트용 User 객체. DB 저장 없이 메모리에서만 사용한다.

    bcrypt 해시는 매 호출 ~100ms 라 함수마다 호출이 누적되면 느려진다.
    필요 시 module-scope fixture 로 캐시 가능 (지금은 수가 적어 그대로).
    """
    now = datetime.now(timezone.utc)
    user = User(
        login_id=login_id,
        username=username,
        email=email,
        password_hash=hash_password(password),
        role=UserRole.USER,
        is_active=is_active,
        agreed_terms_at=now,
        agreed_privacy_at=now,
    )
    user.id = id_
    return user


# ── sign_in: 실패 케이스 ──────────────────────────────


async def test_sign_in_with_unknown_login_id_raises_invalid_credentials() -> None:
    """존재하지 않는 아이디 → InvalidCredentials."""
    service = AuthService(_FakeAuthRepo())  # type: ignore[arg-type]
    with pytest.raises(InvalidCredentials):
        await service.sign_in(login_id="nobody", password="any")


async def test_sign_in_with_wrong_password_raises_invalid_credentials() -> None:
    """비밀번호 불일치 → InvalidCredentials (아이디 존재 여부 노출 X)."""
    user = _make_user(password="correct-pw")
    service = AuthService(_FakeAuthRepo(user=user))  # type: ignore[arg-type]
    with pytest.raises(InvalidCredentials):
        await service.sign_in(login_id=user.login_id, password="wrong-pw")


async def test_sign_in_with_inactive_user_raises_invalid_credentials() -> None:
    user = _make_user(is_active=False)
    service = AuthService(_FakeAuthRepo(user=user))  # type: ignore[arg-type]
    with pytest.raises(InvalidCredentials):
        await service.sign_in(login_id=user.login_id, password="correct-pw")


# ── sign_in: 정상 ────────────────────────────────────


async def test_sign_in_returns_access_and_refresh_tokens_on_success() -> None:
    user = _make_user(password="correct-pw")
    service = AuthService(_FakeAuthRepo(user=user))  # type: ignore[arg-type]

    access, refresh = await service.sign_in(
        login_id=user.login_id, password="correct-pw"
    )

    access_payload = decode_token(access, expected_type="access")
    refresh_payload = decode_token(refresh, expected_type="refresh")
    assert access_payload["sub"] == "1"
    assert refresh_payload["sub"] == "1"
    assert access_payload["role"] == "USER"


# ── sign_up ──────────────────────────────────────────


async def test_sign_up_creates_user_and_returns_tokens() -> None:
    """정상 가입 → repo.add 1회 + (user, access, refresh) 반환."""
    repo = _FakeAuthRepo()
    service = AuthService(repo)  # type: ignore[arg-type]

    user, access, refresh = await service.sign_up(
        login_id="newuser",
        username="새사용자",
        password="abc12345",
        email="new@example.com",
        agreed_marketing=False,
    )

    assert len(repo.added) == 1
    assert user.login_id == "newuser"
    assert user.username == "새사용자"
    assert user.email == "new@example.com"
    assert user.agreed_terms_at is not None
    assert user.agreed_privacy_at is not None
    assert user.agreed_marketing_at is None  # 선택 미동의 → NULL
    decode_token(access, expected_type="access")
    decode_token(refresh, expected_type="refresh")


async def test_sign_up_with_marketing_consent_sets_timestamp() -> None:
    """marketing=True 면 agreed_marketing_at 도 채워진다."""
    repo = _FakeAuthRepo()
    service = AuthService(repo)  # type: ignore[arg-type]

    user, *_ = await service.sign_up(
        login_id="newuser",
        username="새사용자",
        password="abc12345",
        email="new@example.com",
        agreed_marketing=True,
    )
    assert user.agreed_marketing_at is not None


async def test_sign_up_normalizes_email_to_lowercase() -> None:
    """대문자 이메일 입력해도 소문자로 저장."""
    repo = _FakeAuthRepo()
    service = AuthService(repo)  # type: ignore[arg-type]

    user, *_ = await service.sign_up(
        login_id="newuser",
        username="새사용자",
        password="abc12345",
        email="NEW@Example.COM",
        agreed_marketing=False,
    )
    assert user.email == "new@example.com"


async def test_sign_up_rejects_duplicate_login_id() -> None:
    existing = _make_user(login_id="taken")
    service = AuthService(_FakeAuthRepo(user=existing))  # type: ignore[arg-type]

    with pytest.raises(UsernameTaken):
        await service.sign_up(
            login_id="taken",
            username="아무개",
            password="abc12345",
            email="x@y.com",
            agreed_marketing=False,
        )


async def test_sign_up_rejects_duplicate_email() -> None:
    existing = _make_user(login_id="other", email="dup@example.com")
    service = AuthService(_FakeAuthRepo(user=existing))  # type: ignore[arg-type]

    with pytest.raises(EmailTaken):
        await service.sign_up(
            login_id="newuser",
            username="아무개",
            password="abc12345",
            email="DUP@example.com",  # 정규화 후 비교되는지 검증
            agreed_marketing=False,
        )


# ── is_login_id_available ─────────────────────────────


async def test_is_login_id_available_returns_true_when_free() -> None:
    service = AuthService(_FakeAuthRepo())  # type: ignore[arg-type]
    assert await service.is_login_id_available("anything") is True


async def test_is_login_id_available_returns_false_when_taken() -> None:
    user = _make_user(login_id="taken")
    service = AuthService(_FakeAuthRepo(user=user))  # type: ignore[arg-type]
    assert await service.is_login_id_available("taken") is False


# ── refresh_token ────────────────────────────────────


async def test_refresh_token_with_expired_token_raises_token_expired() -> None:
    user = _make_user()
    service = AuthService(_FakeAuthRepo(user=user))  # type: ignore[arg-type]
    expired = create_refresh_token(sub="1", expires_in=timedelta(seconds=-10))
    with pytest.raises(TokenExpired):
        await service.refresh_token(expired)


async def test_refresh_token_rejects_access_token() -> None:
    """access 토큰을 refresh 자리에 넣으면 거부 — type 가드."""
    user = _make_user()
    service = AuthService(_FakeAuthRepo(user=user))  # type: ignore[arg-type]
    access = create_access_token(sub="1", claims={})
    with pytest.raises(TokenExpired):
        await service.refresh_token(access)


async def test_refresh_token_with_unknown_user_raises_invalid_credentials() -> None:
    service = AuthService(_FakeAuthRepo())  # type: ignore[arg-type]
    valid = create_refresh_token(sub="999")
    with pytest.raises(InvalidCredentials):
        await service.refresh_token(valid)


async def test_refresh_token_with_inactive_user_raises_invalid_credentials() -> None:
    user = _make_user(is_active=False)
    service = AuthService(_FakeAuthRepo(user=user))  # type: ignore[arg-type]
    valid = create_refresh_token(sub="1")
    with pytest.raises(InvalidCredentials):
        await service.refresh_token(valid)


async def test_refresh_token_returns_new_access_and_refresh_pair() -> None:
    user = _make_user()
    service = AuthService(_FakeAuthRepo(user=user))  # type: ignore[arg-type]
    old_refresh = create_refresh_token(sub="1")

    new_access, new_refresh = await service.refresh_token(old_refresh)

    access_payload = decode_token(new_access, expected_type="access")
    refresh_payload = decode_token(new_refresh, expected_type="refresh")
    assert access_payload["sub"] == "1"
    assert refresh_payload["sub"] == "1"
    assert access_payload["role"] == "USER"
