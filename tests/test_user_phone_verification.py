"""UserService 전화번호 인증(Octomo QR 방식) 단위 테스트 — DB·Redis·Octomo 없이."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.auth.adapters.ports import PhoneVerificationChallenge
from app.core.exceptions import OtpInvalidError, OtpRateLimitedError
from app.core.security import hash_password
from app.user.models import User, UserRole
from app.user.user_service import UserService

# ── Fakes ────────────────────────────────────────────────────────────────────


class _FakeUserRepo:
    async def delete_social_accounts(self, user_id: int) -> None:
        pass


class _FakePhoneVerifier:
    """issue_challenge/verify 호출을 기록하는 fake. verify 결과는 미리 설정."""

    def __init__(
        self, *, verify_result: bool = True, issue_error: Exception | None = None
    ) -> None:
        self.issued: list[str] = []
        self.verified: list[str] = []
        self.verify_result = verify_result
        self.issue_error = issue_error

    async def issue_challenge(self, phone: str) -> PhoneVerificationChallenge:
        self.issued.append(phone)
        if self.issue_error is not None:
            raise self.issue_error
        return PhoneVerificationChallenge(code="abc123", qr_code="data:image/png;base64,fake")

    async def verify(self, phone: str) -> bool:
        self.verified.append(phone)
        return self.verify_result


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
        return (self._store.pop(key, None) and 1) or 0


# ── 팩토리 ────────────────────────────────────────────────────────────────────


def _make_service(
    *, verify_result: bool = True, issue_error: Exception | None = None
) -> tuple[UserService, _FakePhoneVerifier, _FakeRedis]:
    repo = _FakeUserRepo()
    verifier = _FakePhoneVerifier(verify_result=verify_result, issue_error=issue_error)
    redis = _FakeRedis()
    service = UserService(repo, phone_verifier=verifier, redis=redis)  # type: ignore[arg-type]
    return service, verifier, redis


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
    return u


# ── send_phone_verification ───────────────────────────────────────────────────


async def test_send_phone_verification_returns_challenge_from_verifier() -> None:
    """Octomo 어댑터가 발급한 challenge(코드+QR)를 그대로 반환한다."""
    service, verifier, _ = _make_service()

    challenge = await service.send_phone_verification(phone="01012345678")

    assert challenge.qr_code == "data:image/png;base64,fake"
    assert verifier.issued == ["01012345678"]


async def test_send_phone_verification_rate_limited_within_60s_raises() -> None:
    """60초 이내 재요청은 OtpRateLimitedError 를 raise 한다."""
    service, verifier, _ = _make_service()

    await service.send_phone_verification(phone="01012345678")

    with pytest.raises(OtpRateLimitedError):
        await service.send_phone_verification(phone="01012345678")

    # rate-limit 에 걸린 두 번째 호출은 verifier 까지 도달하지 않아야 함
    assert verifier.issued == ["01012345678"]


async def test_send_phone_verification_releases_rate_lock_when_issue_fails() -> None:
    """Octomo 발급이 실패하면 rate-limit 락을 남기지 않는다 — 재시도가 429 로 막히면 안 됨.

    (회귀: 락을 Octomo 호출 전에 잡고 실패 시 해제 안 해서, 첫 요청이 500 나면
    이후 60초간 모든 재시도가 OtpRateLimitedError 로 떨어지던 버그)
    """
    service, verifier, _ = _make_service(issue_error=RuntimeError("Octomo down"))

    with pytest.raises(RuntimeError):
        await service.send_phone_verification(phone="01012345678")

    # 두 번째 호출은 429 가 아니라 실제 발급 경로(verifier)까지 다시 도달해야 한다
    with pytest.raises(RuntimeError):
        await service.send_phone_verification(phone="01012345678")

    assert verifier.issued == ["01012345678", "01012345678"]


# ── verify_phone ──────────────────────────────────────────────────────────────


async def test_verify_phone_success_sets_phone_and_phone_verified_at() -> None:
    """Octomo 검증 성공 시 user.phone 과 phone_verified_at 이 갱신된다."""
    service, verifier, _ = _make_service(verify_result=True)
    user = _make_user()

    await service.verify_phone(user=user, phone="01099998888")

    assert user.phone == "01099998888"
    assert user.phone_verified_at is not None
    assert verifier.verified == ["01099998888"]


async def test_verify_phone_failure_raises_otp_invalid_and_does_not_change_user() -> None:
    """Octomo 검증 실패(미도착/만료) 시 OtpInvalidError, user 는 변경되지 않는다."""
    service, _, _ = _make_service(verify_result=False)
    user = _make_user()
    original_phone = user.phone

    with pytest.raises(OtpInvalidError):
        await service.verify_phone(user=user, phone="01099998888")

    assert user.phone == original_phone
    assert user.phone_verified_at is None
