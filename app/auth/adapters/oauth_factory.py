"""OAuthProvider 어댑터 팩토리 — provider 이름으로 적절한 어댑터를 반환.

settings 의 client_id / client_secret / redirect_uri 가 누락된 provider 는
RuntimeError — .env 채우라는 메시지로 거절.
"""

from __future__ import annotations

from app.auth.adapters.google_oauth import GoogleOAuthAdapter
from app.auth.adapters.kakao_oauth import KakaoOAuthAdapter
from app.auth.adapters.naver_oauth import NaverOAuthAdapter
from app.auth.adapters.ports import OAuthProvider
from app.auth.models import SocialProvider
from app.core.config import Settings
from app.core.exceptions import SocialProviderNotConfiguredError


def build_oauth_provider(provider: SocialProvider, settings_obj: Settings) -> OAuthProvider:
    """provider 별 어댑터 생성. config 누락 시 명시적 에러."""
    if provider is SocialProvider.KAKAO:
        if not (settings_obj.kakao_client_id and settings_obj.kakao_redirect_uri):
            raise SocialProviderNotConfiguredError(
                message="카카오 OAuth 설정 누락 (KAKAO_CLIENT_ID / KAKAO_REDIRECT_URI)"
            )
        return KakaoOAuthAdapter(
            client_id=settings_obj.kakao_client_id,
            client_secret=settings_obj.kakao_client_secret,
            redirect_uri=settings_obj.kakao_redirect_uri,
        )

    if provider is SocialProvider.NAVER:
        missing = [
            n
            for n, v in [
                ("NAVER_CLIENT_ID", settings_obj.naver_client_id),
                ("NAVER_CLIENT_SECRET", settings_obj.naver_client_secret),
                ("NAVER_REDIRECT_URI", settings_obj.naver_redirect_uri),
            ]
            if not v
        ]
        if missing:
            raise SocialProviderNotConfiguredError(
                message=f"네이버 OAuth 설정 누락: {', '.join(missing)}"
            )
        return NaverOAuthAdapter(
            client_id=settings_obj.naver_client_id,  # type: ignore[arg-type]
            client_secret=settings_obj.naver_client_secret,  # type: ignore[arg-type]
            redirect_uri=settings_obj.naver_redirect_uri,  # type: ignore[arg-type]
        )

    if provider is SocialProvider.GOOGLE:
        missing = [
            n
            for n, v in [
                ("GOOGLE_CLIENT_ID", settings_obj.google_client_id),
                ("GOOGLE_CLIENT_SECRET", settings_obj.google_client_secret),
                ("GOOGLE_REDIRECT_URI", settings_obj.google_redirect_uri),
            ]
            if not v
        ]
        if missing:
            raise SocialProviderNotConfiguredError(
                message=f"구글 OAuth 설정 누락: {', '.join(missing)}"
            )
        return GoogleOAuthAdapter(
            client_id=settings_obj.google_client_id,  # type: ignore[arg-type]
            client_secret=settings_obj.google_client_secret,  # type: ignore[arg-type]
            redirect_uri=settings_obj.google_redirect_uri,  # type: ignore[arg-type]
        )

    raise ValueError(f"Unknown social provider: {provider}")
