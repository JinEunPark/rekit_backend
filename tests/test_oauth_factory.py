"""OAuth factory 테스트 — provider 별 어댑터 생성 + config 누락 거절."""

from __future__ import annotations

from typing import Any

import pytest

from app.auth.adapters.google_oauth import GoogleOAuthAdapter
from app.auth.adapters.kakao_oauth import KakaoOAuthAdapter
from app.auth.adapters.naver_oauth import NaverOAuthAdapter
from app.auth.adapters.oauth_factory import build_oauth_provider
from app.auth.models import SocialProvider
from app.core.config import Settings
from app.core.exceptions import SocialProviderNotConfiguredError


def _settings(**overrides: Any) -> Settings:
    """필수 settings 만 채운 기본 — overrides 로 OAuth 자리만 변경."""
    return Settings.model_construct(**overrides)


def test_factory_returns_kakao_adapter_for_kakao_provider() -> None:
    settings = _settings(
        kakao_client_id="kid",
        kakao_client_secret="ksecret",
        kakao_redirect_uri="https://x/cb/kakao",
    )
    adapter = build_oauth_provider(SocialProvider.KAKAO, settings)
    assert isinstance(adapter, KakaoOAuthAdapter)


def test_factory_kakao_allows_missing_client_secret() -> None:
    """카카오는 client_secret 사용 OFF 콘솔 설정도 가능 — None 허용."""
    settings = _settings(
        kakao_client_id="kid",
        kakao_client_secret=None,
        kakao_redirect_uri="https://x/cb/kakao",
    )
    adapter = build_oauth_provider(SocialProvider.KAKAO, settings)
    assert isinstance(adapter, KakaoOAuthAdapter)
    assert adapter.client_secret is None


def test_factory_returns_naver_adapter_for_naver_provider() -> None:
    settings = _settings(
        naver_client_id="nid",
        naver_client_secret="nsecret",
        naver_redirect_uri="https://x/cb/naver",
    )
    adapter = build_oauth_provider(SocialProvider.NAVER, settings)
    assert isinstance(adapter, NaverOAuthAdapter)


def test_factory_returns_google_adapter_for_google_provider() -> None:
    settings = _settings(
        google_client_id="gid",
        google_client_secret="gsecret",
        google_redirect_uri="https://x/cb/google",
    )
    adapter = build_oauth_provider(SocialProvider.GOOGLE, settings)
    assert isinstance(adapter, GoogleOAuthAdapter)


def test_factory_raises_when_kakao_config_missing() -> None:
    settings = _settings(kakao_client_id=None, kakao_redirect_uri=None)
    with pytest.raises(SocialProviderNotConfiguredError, match="카카오 OAuth"):
        build_oauth_provider(SocialProvider.KAKAO, settings)


def test_factory_raises_when_naver_config_missing() -> None:
    settings = _settings(naver_client_id="nid")  # secret/redirect 누락
    with pytest.raises(SocialProviderNotConfiguredError, match="네이버 OAuth"):
        build_oauth_provider(SocialProvider.NAVER, settings)


def test_factory_raises_when_google_config_missing() -> None:
    settings = _settings(google_client_id="gid")  # secret/redirect 누락
    with pytest.raises(SocialProviderNotConfiguredError, match="구글 OAuth"):
        build_oauth_provider(SocialProvider.GOOGLE, settings)
