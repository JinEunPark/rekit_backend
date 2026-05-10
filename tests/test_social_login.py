"""소셜 로그인 service 단위 테스트.

DB 없이 fake repo + fake OAuth provider 로 도메인 로직 검증.
- 기존 SocialAccount 매칭 → 즉시 로그인
- 미매칭 → needsSignUp + tempToken
- 이메일 동의 누락 → SocialEmailRequired
- social_sign_up: tempToken → User + SocialAccount 생성 + 토큰
- 중복 login_id / email → UsernameTaken / EmailTaken
"""

from __future__ import annotations

import pytest

from app.auth.adapters.ports import OAuthProvider, SocialProfile
from app.auth.auth_service import AuthService
from app.auth.models import SocialAccount, SocialProvider
from app.common.email import ConsoleEmailSender
from app.core.exceptions import (
    EmailTaken,
    InvalidCredentials,
    SocialEmailRequired,
    TokenExpired,
    UsernameTaken,
)
from app.core.security import (
    create_social_signup_token,
    decode_social_signup_token,
)
from app.user.models import User
from tests.conftest import make_user

# ── Fakes ───────────────────────────────────────────────


class _FakeOAuth:
    """OAuthProvider Protocol 의 fake — 미리 정해둔 SocialProfile 반환."""

    def __init__(self, profile: SocialProfile) -> None:
        self.profile = profile
        self.calls: list[tuple[str, str | None]] = []

    async def exchange_code(
        self, code: str, state: str | None = None
    ) -> SocialProfile:
        self.calls.append((code, state))
        return self.profile


class _FakeAuthRepo:
    """소셜 로그인 케이스 한정 fake. 기존 _FakeAuthRepo (test_auth_service) 와
    분리해 둠 — SocialAccount 저장 로직만 확인."""

    def __init__(self, user: User | None = None) -> None:
        self._user = user
        self._socials: list[SocialAccount] = []
        self.added_users: list[User] = []
        self.added_socials: list[SocialAccount] = []

    async def get_by_id(self, user_id: int) -> User | None:
        if self._user is None:
            return None
        return self._user if self._user.id == user_id else None

    async def exists_by_login_id(self, login_id: str) -> bool:
        return self._user is not None and self._user.login_id == login_id

    async def exists_by_email(self, email: str) -> bool:
        return self._user is not None and self._user.email == email

    async def get_social_account(
        self, provider: SocialProvider, social_id: str
    ) -> SocialAccount | None:
        for s in self._socials:
            if s.provider == provider and s.social_id == social_id:
                return s
        return None

    async def add(self, user: User) -> User:
        user.id = (self._user.id + 1) if self._user else 100
        self.added_users.append(user)
        self._user = user
        return user

    async def add_social_account(self, account: SocialAccount) -> SocialAccount:
        self._socials.append(account)
        self.added_socials.append(account)
        return account


def _make_service(repo: object) -> AuthService:
    return AuthService(repo, email_sender=ConsoleEmailSender())  # type: ignore[arg-type]


# ── social_login: 기존 사용자 ─────────────────────────────


async def test_social_login_returns_tokens_when_social_account_exists() -> None:
    # Arrange — 기존 user 와 그 user 에 연결된 SocialAccount
    user = make_user(user_id=10, login_id="existing_user", email="user@example.com")
    repo = _FakeAuthRepo(user=user)
    repo._socials.append(
        SocialAccount(
            user_id=user.id,
            provider=SocialProvider.KAKAO,
            social_id="kakao-123",
            email_at_link="user@example.com",
        )
    )
    oauth = _FakeOAuth(
        SocialProfile(provider="kakao", social_id="kakao-123", email="user@example.com", name="홍길동")
    )
    service = _make_service(repo)

    # Act
    result = await service.social_login(SocialProvider.KAKAO, oauth, code="abc", state=None)

    # Assert
    assert result.needs_sign_up is False
    assert result.access_token is not None
    assert result.refresh_token is not None
    assert result.must_change_password is False


# ── social_login: 신규 사용자 ─────────────────────────────


async def test_social_login_returns_temp_token_when_no_social_match() -> None:
    """매칭되는 SocialAccount 없음 → needsSignUp=true + tempToken 발급."""
    repo = _FakeAuthRepo()  # 빈 DB
    oauth = _FakeOAuth(
        SocialProfile(
            provider="naver", social_id="naver-xyz", email="new@example.com", name="신규"
        )
    )
    service = _make_service(repo)

    result = await service.social_login(SocialProvider.NAVER, oauth, code="abc", state="s1")

    assert result.needs_sign_up is True
    assert result.temp_token is not None
    assert result.email == "new@example.com"
    assert result.suggested_name == "신규"
    assert result.access_token is None

    # tempToken 안에 (provider, social_id, email) 가 들어있는지 — 신뢰 가능 검증
    payload = decode_social_signup_token(result.temp_token)
    assert payload["provider"] == "naver"
    assert payload["social_id"] == "naver-xyz"
    assert payload["email"] == "new@example.com"


async def test_social_login_passes_state_to_oauth_adapter() -> None:
    """네이버처럼 state 를 token exchange 에 써야 하는 경우 — 그대로 전달되는지."""
    repo = _FakeAuthRepo()
    oauth = _FakeOAuth(
        SocialProfile(provider="naver", social_id="x", email="a@b.com", name=None)
    )
    service = _make_service(repo)

    await service.social_login(SocialProvider.NAVER, oauth, code="c", state="my-state")

    assert oauth.calls == [("c", "my-state")]


async def test_social_login_raises_when_email_missing() -> None:
    """카카오 사용자가 이메일 동의 거부한 경우 — 422 거절."""
    repo = _FakeAuthRepo()
    oauth = _FakeOAuth(
        SocialProfile(provider="kakao", social_id="k1", email=None, name="익명")
    )
    service = _make_service(repo)

    with pytest.raises(SocialEmailRequired):
        await service.social_login(SocialProvider.KAKAO, oauth, code="c")


async def test_social_login_raises_invalid_credentials_when_linked_user_inactive() -> None:
    """SocialAccount 는 있지만 연결된 user 가 is_active=False — 차단."""
    user = make_user(user_id=1, is_active=False)
    repo = _FakeAuthRepo(user=user)
    repo._socials.append(
        SocialAccount(
            user_id=user.id,
            provider=SocialProvider.GOOGLE,
            social_id="g1",
            email_at_link=user.email,
        )
    )
    oauth = _FakeOAuth(
        SocialProfile(provider="google", social_id="g1", email=user.email, name="홍")
    )
    service = _make_service(repo)

    with pytest.raises(InvalidCredentials):
        await service.social_login(SocialProvider.GOOGLE, oauth, code="c")


# ── social_sign_up ──────────────────────────────────────


async def test_social_sign_up_creates_user_and_social_account() -> None:
    repo = _FakeAuthRepo()
    service = _make_service(repo)

    temp = create_social_signup_token(
        provider="kakao",
        social_id="kakao-999",
        email="welcome@example.com",
        name="환영",
    )

    user, access, refresh = await service.social_sign_up(
        temp_token=temp,
        login_id="welcome01",
        username="환영",
        agreed_marketing=True,
    )

    # User 생성됨
    assert user.login_id == "welcome01"
    assert user.email == "welcome@example.com"
    assert user.agreed_marketing_at is not None
    # SocialAccount 도 같이
    assert len(repo.added_socials) == 1
    sa = repo.added_socials[0]
    assert sa.provider == SocialProvider.KAKAO
    assert sa.social_id == "kakao-999"
    assert sa.email_at_link == "welcome@example.com"
    assert sa.user_id == user.id
    # 토큰 발급
    assert access and refresh


async def test_social_sign_up_rejects_duplicate_login_id() -> None:
    existing = make_user(user_id=1, login_id="taken", email="other@example.com")
    repo = _FakeAuthRepo(user=existing)
    service = _make_service(repo)

    temp = create_social_signup_token(
        provider="naver", social_id="n1", email="new@example.com", name=None
    )

    with pytest.raises(UsernameTaken):
        await service.social_sign_up(
            temp_token=temp,
            login_id="taken",
            username="아무개",
            agreed_marketing=False,
        )


async def test_social_sign_up_rejects_duplicate_email() -> None:
    """tempToken 의 email 이 이미 다른 사용자가 쓰는 경우 — 자동 연결 안 함."""
    existing = make_user(user_id=1, login_id="user1", email="dup@example.com")
    repo = _FakeAuthRepo(user=existing)
    service = _make_service(repo)

    temp = create_social_signup_token(
        provider="google", social_id="g1", email="dup@example.com", name=None
    )

    with pytest.raises(EmailTaken):
        await service.social_sign_up(
            temp_token=temp,
            login_id="newuser",
            username="신규",
            agreed_marketing=False,
        )


async def test_social_sign_up_rejects_expired_token() -> None:
    """잘못된/위조 tempToken — TokenExpired."""
    repo = _FakeAuthRepo()
    service = _make_service(repo)

    with pytest.raises(TokenExpired):
        await service.social_sign_up(
            temp_token="invalid.jwt.string",
            login_id="newuser",
            username="신규",
            agreed_marketing=False,
        )


def test_create_and_decode_social_signup_token_roundtrip() -> None:
    """토큰 인코드 → 디코드 시 claim 보존."""
    token = create_social_signup_token(
        provider="google", social_id="g123", email="g@x.com", name="이름"
    )
    payload = decode_social_signup_token(token)
    assert payload["provider"] == "google"
    assert payload["social_id"] == "g123"
    assert payload["email"] == "g@x.com"
    assert payload["name"] == "이름"
    assert payload["type"] == "social-signup"


def test_decode_social_signup_token_rejects_other_token_types() -> None:
    """access 토큰을 social-signup 자리에 못 씀."""
    from app.core.security import create_access_token

    access = create_access_token(sub="1", claims={})
    with pytest.raises(TokenExpired):
        decode_social_signup_token(access)
