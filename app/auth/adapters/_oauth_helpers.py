"""OAuth 어댑터 공용 헬퍼.

3개 PG(Kakao/Naver/Google) 어댑터가 공통으로 쓰는 작은 유틸. 어댑터 내부에서
httpx 의 raw 예외를 도메인 예외(SocialOAuthFailed) 로 변환해 service 가
httpx 를 직접 import 하지 않도록 한다 (CLAUDE.md "service 는 port 로만" 규칙).
"""

from __future__ import annotations

import httpx

from app.core.exceptions import SocialOAuthFailed


def translate_oauth_error(exc: httpx.HTTPError, *, provider: str) -> SocialOAuthFailed:
    """httpx 예외 → SocialOAuthFailed 도메인 예외로 변환.

    - HTTPStatusError (4xx/5xx 응답): code 만료 / redirect_uri 불일치 /
      client credentials 불일치 등 PG 거절. status code 를 메시지에 포함.
    - RequestError (네트워크/타임아웃/TLS): PG 자체 도달 불가.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return SocialOAuthFailed(
            message=f"{provider} OAuth 응답 오류 ({exc.response.status_code})"
        )
    return SocialOAuthFailed(message=f"{provider} OAuth 통신 실패: {exc}")
