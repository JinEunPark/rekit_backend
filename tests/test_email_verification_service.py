"""이메일 인증 서비스 단위 테스트 — TDD Red phase.

DB·Redis·이메일 없이 FakeRedis + FakeEmailSender + FakeAuthRepo 로 검증.

검증 범위:
- send_email_verification_code: Redis 저장 / 이메일 태스크 등록 / rate-limit
- verify_email_code: 코드 일치 → verified_token 반환 / 불일치·만료 → 에러
- sign_up (수정): verified_token 에서 이메일 추출 / 만료 토큰 거절
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi import BackgroundTasks

from app.auth.auth_repository import AuthRepository
from app.auth.auth_schemas import SignUpRequest
from app.auth.auth_service import AuthService
from app.common.email import EmailSender
from app.core.exceptions import InvalidVerificationCode, UsernameTaken, VerificationRateLimited
from app.core.security import create_email_verified_token
from tests.conftest import FakeRedis


# ── Fake EmailSender ───────────────────────────────────────────────


class _FakeEmailSender:
    """발송 내역을 records 에 기록한다."""

    def __init__(self) -> None:
        self.records: list[dict[str, str]] = []

    async def send(
        self, *, to: str, subject: str, body: str, html_body: str | None = None
    ) -> None:
        self.records.append({"to": to, "subject": subject, "body": body})


_: EmailSender = _FakeEmailSender()  # type: ignore[assignment]


# ── Fake AuthRepo (최소 구현) ──────────────────────────────────────


class _FakeAuthRepo:
    def __init__(self) -> None:
        self._users: list[Any] = []

    async def get_by_login_id(self, login_id: str) -> Any:
        return next((u for u in self._users if u.login_id == login_id), None)

    async def get_by_email(self, email: str) -> Any:
        return next((u for u in self._users if u.email == email), None)

    async def exists_by_login_id(self, login_id: str) -> bool:
        return any(u.login_id == login_id for u in self._users)

    async def exists_by_email(self, email: str) -> bool:
        return any(u.email == email for u in self._users)

    async def add(self, user: Any) -> Any:
        user.id = len(self._users) + 1
        self._users.append(user)
        return user

    async def add_social_account(self, account: Any) -> None:
        pass


# ── Service 팩토리 ────────────────────────────────────────────────


def _make_service(
    redis: FakeRedis | None = None,
    email_sender: _FakeEmailSender | None = None,
    repo: _FakeAuthRepo | None = None,
) -> tuple[AuthService, FakeRedis, _FakeEmailSender]:
    r = redis or FakeRedis()
    e = email_sender or _FakeEmailSender()
    repo_ = repo or _FakeAuthRepo()
    svc = AuthService(repo_, e, r)  # type: ignore[arg-type]
    return svc, r, e


# ── send_email_verification_code ─────────────────────────────────


async def test_send_code_stores_code_in_redis() -> None:
    """코드를 발송하면 Redis 에 6자리 숫자 코드가 저장된다."""
    svc, redis, _ = _make_service()
    bg = BackgroundTasks()

    await svc.send_email_verification_code("user@example.com", bg)

    stored = await redis.get("email:verify:user@example.com")
    assert stored is not None
    assert len(stored) == 6
    assert stored.isdigit()


async def test_send_code_queues_email_background_task() -> None:
    """코드를 발송하면 BackgroundTasks 에 이메일 태스크가 1개 등록된다."""
    svc, _, _ = _make_service()
    bg = BackgroundTasks()

    await svc.send_email_verification_code("user@example.com", bg)

    assert len(bg.tasks) == 1
    assert bg.tasks[0].kwargs["to"] == "user@example.com"


async def test_send_code_sets_rate_limit_key() -> None:
    """코드 발송 후 rate-limit 키가 Redis 에 저장된다."""
    svc, redis, _ = _make_service()
    bg = BackgroundTasks()

    await svc.send_email_verification_code("user@example.com", bg)

    assert await redis.exists("email:verify:rate:user@example.com") == 1


async def test_send_code_rate_limited_within_60s() -> None:
    """rate-limit 키가 살아있는 동안 재발송 시 VerificationRateLimited 를 올린다."""
    svc, redis, _ = _make_service()
    bg = BackgroundTasks()

    await svc.send_email_verification_code("user@example.com", bg)

    with pytest.raises(VerificationRateLimited):
        await svc.send_email_verification_code("user@example.com", bg)


# ── verify_email_code ────────────────────────────────────────────


async def test_verify_correct_code_returns_verified_token() -> None:
    """올바른 코드 입력 → verified_token JWT 가 반환된다."""
    svc, redis, _ = _make_service()
    await redis.set("email:verify:user@example.com", "123456")

    token = await svc.verify_email_code("user@example.com", "123456")

    assert isinstance(token, str)
    assert len(token) > 10


async def test_verify_correct_code_token_contains_email() -> None:
    """반환된 verified_token 을 디코드하면 email 이 포함된다."""
    from app.core.security import decode_email_verified_token

    svc, redis, _ = _make_service()
    await redis.set("email:verify:user@example.com", "123456")

    token = await svc.verify_email_code("user@example.com", "123456")
    payload = decode_email_verified_token(token)

    assert payload["email"] == "user@example.com"


async def test_verify_wrong_code_raises() -> None:
    """틀린 코드 입력 → InvalidVerificationCode."""
    svc, redis, _ = _make_service()
    await redis.set("email:verify:user@example.com", "123456")

    with pytest.raises(InvalidVerificationCode):
        await svc.verify_email_code("user@example.com", "000000")


async def test_verify_missing_code_raises() -> None:
    """Redis 에 코드 없음(만료/미발송) → InvalidVerificationCode."""
    svc, _, _ = _make_service()

    with pytest.raises(InvalidVerificationCode):
        await svc.verify_email_code("user@example.com", "123456")


async def test_verify_code_deleted_after_use() -> None:
    """코드 인증 성공 후 Redis 에서 코드가 삭제된다 (일회용)."""
    svc, redis, _ = _make_service()
    await redis.set("email:verify:user@example.com", "123456")

    await svc.verify_email_code("user@example.com", "123456")

    assert await redis.get("email:verify:user@example.com") is None


# ── sign_up (verified_token 기반) ────────────────────────────────


async def test_sign_up_uses_email_from_verified_token() -> None:
    """sign_up 은 verified_token 에서 이메일을 추출해 가입한다."""
    svc, _, _ = _make_service()
    token = create_email_verified_token(email="verified@example.com")

    user, _, _ = await svc.sign_up(
        SignUpRequest.model_validate(
            {
                "verifiedToken": token,
                "loginId": "newuser01",
                "username": "홍길동",
                "password": "Password1",
                "agreedTerms": True,
                "agreedPrivacy": True,
            }
        )
    )

    assert user.email == "verified@example.com"


async def test_sign_up_with_expired_verified_token_raises() -> None:
    """만료된 verified_token 으로 가입 시도 → TokenExpired."""
    from app.core.exceptions import TokenExpired

    svc, _, _ = _make_service()
    expired_token = create_email_verified_token(
        email="user@example.com",
        expires_in=timedelta(seconds=-1),
    )

    with pytest.raises(TokenExpired):
        await svc.sign_up(
            SignUpRequest.model_validate(
                {
                    "verifiedToken": expired_token,
                    "loginId": "newuser01",
                    "username": "홍길동",
                    "password": "Password1",
                    "agreedTerms": True,
                    "agreedPrivacy": True,
                }
            )
        )


async def test_sign_up_duplicate_login_id_raises() -> None:
    """verified_token 이 유효해도 login_id 중복 시 UsernameTaken."""
    from app.user.models import User, UserRole
    from datetime import UTC, datetime

    repo = _FakeAuthRepo()
    existing = User(
        login_id="taken_id",
        username="기존유저",
        email="other@example.com",
        password_hash="x",
        role=UserRole.USER,
        is_active=True,
    )
    existing.id = 1
    existing.created_at = datetime.now(UTC)
    repo._users.append(existing)

    svc, _, _ = _make_service(repo=repo)
    token = create_email_verified_token(email="new@example.com")

    with pytest.raises(UsernameTaken):
        await svc.sign_up(
            SignUpRequest.model_validate(
                {
                    "verifiedToken": token,
                    "loginId": "taken_id",
                    "username": "홍길동",
                    "password": "Password1",
                    "agreedTerms": True,
                    "agreedPrivacy": True,
                }
            )
        )
