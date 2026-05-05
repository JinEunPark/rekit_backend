"""auth 모듈의 외부 통합 ports (Protocol).

본인인증 PG(TOSS/NICE/KCB)와 소셜 OAuth(Kakao/Naver) 같은 외부 시스템은
service 가 직접 import 하지 않고 이 Protocol 에만 의존한다.
구현체는 `app.auth.adapters.<provider>.py` 에 두고,
와이어링은 `app.core.deps` 에서 한다.
"""

from typing import Protocol


class OtpSender(Protocol):
    """SMS OTP 발송기 — 회원가입/비번재설정 1차 인증."""

    async def send(self, phone: str) -> str:
        """OTP 발송 후 verify_token 반환."""
        ...

    async def verify(self, verify_token: str, code: str) -> bool:
        """code 일치 여부."""
        ...


class IdentityVerifier(Protocol):
    """본인인증 PG 어댑터 — TOSS/NICE/KCB 통합 인터페이스.

    실제 인증 UI 는 PG SDK 가 처리하고, 콜백으로 받은 결과 페이로드만 검증한다.
    """

    async def verify_callback(self, payload: dict[str, str]) -> "IdentityVerifyResult":
        """PG 콜백 페이로드 검증 → CI/DI/이름/생년월일/성별 반환."""
        ...


class SocialOAuthProvider(Protocol):
    """소셜 로그인 OAuth 어댑터 — Kakao/Naver."""

    async def exchange_code(self, code: str, state: str) -> "SocialProfile":
        """authorization_code → access_token → 프로필 조회."""
        ...


# ── 결과 DTO (port 가 반환하는 데이터 모양) ──────────────────────


class IdentityVerifyResult:
    """본인인증 결과. dataclass 로 교체해도 무방."""

    ci: str
    di: str
    name: str
    phone: str
    birth_date: str  # YYYY-MM-DD
    gender: str  # MALE/FEMALE


class SocialProfile:
    provider: str  # kakao/naver
    provider_user_id: str
    email: str | None
    name: str | None
