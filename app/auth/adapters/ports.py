"""auth 모듈의 외부 통합 ports (Protocol).

Octomo(전화번호 인증)와 소셜 OAuth(Kakao/Naver/Google) 같은 외부 시스템은
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
class PhoneVerificationChallenge:
    """전화번호 인증 1단계(issue) 결과 — 프론트에 그대로 반환된다."""

    code: str  # Octomo /message/exists 조회에 쓰이는 원본 값
    qr_code: str  # "data:image/png;base64,..." — 프론트가 <img> 로 바로 표시


# ── Port (Protocol) ─────────────────────────────────────


class PhoneVerifier(Protocol):
    """전화번호 소유 확인 — Octomo MO 인증(QR 방식) 어댑터 인터페이스.

    서버가 SMS 를 발송하지 않는다. issue_challenge 는 코드를 생성·저장하고
    그 코드가 담긴 SMS QR 이미지를 Octomo 에서 발급받아 반환할 뿐 — 실제
    발송(스캔 후 전송)은 사용자가 직접 한다. verify 는 "그 문자가 실제로
    도착했는지" PG(Octomo) 에 조회한다.
    """

    async def issue_challenge(self, phone: str) -> PhoneVerificationChallenge:
        """코드를 생성·저장하고, 그 코드의 SMS QR 을 발급해 함께 반환한다."""
        ...

    async def verify(self, phone: str) -> bool:
        """이 phone 에 대해 발급해둔 코드가 담긴 메시지가 최근 도착했는지 확인한다.

        QR 방식이라 사용자는 코드 값 자체를 본 적이 없다 — 그래서 `code`를
        인자로 받지 않는다. 검증 대상 코드는 `issue_challenge`가 저장해둔
        값을 내부적으로 재조회한다.
        """
        ...


class OAuthProvider(Protocol):
    """소셜 로그인 OAuth 어댑터 — Kakao/Naver/Google.

    프론트에서 PG 동의 페이지로 redirect → 사용자 동의 → ?code=... 받음 →
    이 어댑터가 code 로 access_token 교환 후 사용자 프로필 조회.

    state 검증은 프론트 책임 — 서버는 받아서 token exchange body 에 그대로 전달
    (네이버는 token exchange 시 state 가 필수).
    """

    async def exchange_code(self, code: str, state: str | None = None) -> SocialProfile: ...
