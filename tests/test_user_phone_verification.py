"""UserService 전화번호 인증 단위 테스트 — DB·Redis 없이."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.exceptions import OtpInvalid, OtpRateLimited
from app.core.security import hash_password
from app.user.models import Gender, User, UserRole
from app.user.user_service import UserService


# ── Fakes ────────────────────────────────────────────────────────────────────


class _FakeUserRepo:
    async def delete_social_accounts(self, user_id: int) -> None:
        pass


class _FakeSmsSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, phone: str, message: str) -> None:
        self.sent.append((phone, message))


class _FakeRedis:
    """dict 기반 인메모리 Redis stub. SET nx / GET / DELETE / ex TTL(무시) 지원."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> str | None:
        if nx and key in self._store:
            return None
        self._store[key] = value
        return "OK"

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, key: str) -> int:
        return self._store.pop(key, None) and 1 or 0


# ── 팩토리 ────────────────────────────────────────────────────────────────────


def _make_service() -> tuple[UserService, _FakeSmsSender, _FakeRedis]:
    repo = _FakeUserRepo()
    sms = _FakeSmsSender()
    redis = _FakeRedis()
    service = UserService(repo, sms_sender=sms, redis=redis)  # type: ignore[arg-type]
    return service, sms, redis


def _make_user() -> User:
    now = datetime.now(UTC)
    u = User(
        login_id="testuser",
        email="test@example.com",
        password_hash=hash_password("abc12345"),
        username="테스트",
        role=UserRole.USER,
        is_active=True,
        must_change_password=False,
        agreed_terms_at=now,
        agreed_privacy_at=now,
    )
    u.id = 1
    u.phone = "01000000000"
    u.gender = Gender.MALE
    return u


# ── send_phone_verification ───────────────────────────────────────────────────


async def test_send_stores_otp_in_redis_and_sends_sms() -> None:
    """OTP 발송 시 Redis 에 코드가 저장되고 SMS 어댑터가 호출된다."""
    service, sms, redis = _make_service()

    await service.send_phone_verification(phone="01012345678")

    stored = await redis.get("sms:verify:01012345678")
    assert stored is not None and len(stored) == 6 and stored.isdigit()
    assert len(sms.sent) == 1
    phone, message = sms.sent[0]
    assert phone == "01012345678"
    assert stored in message  # OTP 코드가 메시지에 포함


async def test_send_rate_limit_blocks_second_request() -> None:
    """60초 이내 재요청은 OtpRateLimited 를 raise 한다."""
    service, _, _ = _make_service()

    await service.send_phone_verification(phone="01012345678")

    with pytest.raises(OtpRateLimited):
        await service.send_phone_verification(phone="01012345678")


# ── verify_phone ──────────────────────────────────────────────────────────────


async def test_verify_phone_updates_user_phone_and_verified_at() -> None:
    """올바른 코드 입력 시 user.phone 과 phone_verified_at 이 갱신된다."""
    service, _, redis = _make_service()
    user = _make_user()
    await redis.set("sms:verify:01099998888", "654321")

    await service.verify_phone(user=user, phone="01099998888", code="654321")

    assert user.phone == "01099998888"
    assert user.phone_verified_at is not None


async def test_verify_phone_deletes_otp_after_success() -> None:
    """검증 성공 후 Redis 키가 삭제된다 — 재사용 방지."""
    service, _, redis = _make_service()
    user = _make_user()
    await redis.set("sms:verify:01099998888", "111111")

    await service.verify_phone(user=user, phone="01099998888", code="111111")

    assert await redis.get("sms:verify:01099998888") is None


async def test_verify_phone_raises_on_wrong_code() -> None:
    """코드 불일치 시 OtpInvalid — user 는 변경되지 않는다."""
    service, _, redis = _make_service()
    user = _make_user()
    original_phone = user.phone
    await redis.set("sms:verify:01099998888", "123456")

    with pytest.raises(OtpInvalid):
        await service.verify_phone(user=user, phone="01099998888", code="999999")

    assert user.phone == original_phone
    assert user.phone_verified_at is None


async def test_verify_phone_raises_when_otp_expired() -> None:
    """Redis 에 키가 없으면(만료) OtpInvalid."""
    service, _, _ = _make_service()
    user = _make_user()

    with pytest.raises(OtpInvalid):
        await service.verify_phone(user=user, phone="01099998888", code="123456")
