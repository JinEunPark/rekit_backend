"""auth 모듈의 외부 통합 ports (Protocol).

본인인증 PG(TOSS/NICE/KCB)와 소셜 OAuth(Kakao/Naver/Google) 같은 외부 시스템은
service 가 직접 import 하지 않고 이 Protocol 에만 의존한다.
구현체는 `app.auth.adapters.<provider>.py` 에 두고,
와이어링은 `app.core.deps` 에서 한다.
"""

from dataclasses import dataclass
from typing import Protocol


# ── 결과 DTO ────────────────────────────────────────────


@dataclass(frozen=True)
class SocialProfile:
    """OAuth 어댑터가 반환하는 통합 사용자 프로필.

    각 PG 의 응답 형태가 달라도 이 모양으로 통일해서 service 가 다룬다.
    `email` 은 사용자가 동의 안 했으면 None — service 가 거부 처리.
    """

    provider: str  # "kakao" | "naver" | "google" — SocialProvider.value 와 일치
    social_id: str  # PG 의 사용자 ID. 카카오 long / 네이버·구글 string — 모두 string 으로
    email: str | None
    name: str | None


@dataclass(frozen=True)
class IdentityVerifyResult:
    """본인인증 PG 결과. CI/DI 는 암호화 저장 책임은 service."""

    ci: str
    di: str
    name: str
    phone: str
    birth_date: str  # YYYY-MM-DD
    gender: str  # MALE / FEMALE


# ── Port (Protocol) ─────────────────────────────────────


class OtpSender(Protocol):
    """SMS OTP 발송기 — 회원가입/비번재설정 1차 인증."""

    async def send(self, phone: str) -> str:
        """OTP 발송 후 verify_token 반환."""
        ...

    async def verify(self, verify_token: str, code: str) -> bool:
        """code 일치 여부."""
        ...


class IdentityVerifier(Protocol):
    """본인인증 PG 어댑터 — TOSS/NICE/KCB 통합 인터페이스."""

    async def verify_callback(self, payload: dict[str, str]) -> IdentityVerifyResult: ...


class OAuthProvider(Protocol):
    """소셜 로그인 OAuth 어댑터 — Kakao/Naver/Google.

    프론트에서 PG 동의 페이지로 redirect → 사용자 동의 → ?code=... 받음 →
    이 어댑터가 code 로 access_token 교환 후 사용자 프로필 조회.

    state 검증은 프론트 책임 — 서버는 받아서 token exchange body 에 그대로 전달
    (네이버는 token exchange 시 state 가 필수).
    """

    async def exchange_code(self, code: str, state: str | None = None) -> SocialProfile: ...
