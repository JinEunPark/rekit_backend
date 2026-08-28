"""소셜 로그인 라우터 통합 테스트 — DB 없이 동작 가능한 케이스만.

전체 가입 → 재로그인 흐름은 service 단위 (test_social_login.py) 에서 이미 검증.
여기는 라우터 레이어의 dependency_overrides / path 검증 / 422 응답만 확인.

DB 가 필요한 multi-call 통합은 SQLAlchemy async + TestClient 의 event loop
충돌로 안정적이지 않음 — 운영 시 manual curl 또는 e2e 테스트 환경 별도 분리.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth.adapters.ports import OAuthProvider, SocialProfile
from app.auth.models import SocialProvider
from app.core.deps import get_oauth_provider
from app.main import app


class _FakeOAuth:
    def __init__(self, profile: SocialProfile) -> None:
        self.profile = profile

    async def exchange_code(
        self, code: str, state: str | None = None
    ) -> SocialProfile:
        return self.profile


def _override_with(profile: SocialProfile) -> Callable[[SocialProvider], OAuthProvider]:
    def _fake(provider: SocialProvider) -> OAuthProvider:
        return _FakeOAuth(profile)

    return _fake


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_kakao_callback_rejects_when_email_consent_missing(client: TestClient) -> None:
    """카카오 사용자가 이메일 동의 거부 → 422 SOCIAL_EMAIL_REQUIRED.

    OAuth 어댑터가 email=None 반환 — DB 도달 전에 service 가 거절.
    """
    no_email = SocialProfile(
        provider="kakao", social_id="k-99", email=None, name="익명"
    )
    app.dependency_overrides[get_oauth_provider] = _override_with(no_email)

    res = client.post("/api/v1/auth/social/kakao/callback", json={"code": "x"})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "SOCIAL_EMAIL_REQUIRED"


def test_invalid_provider_path_returns_validation_error(client: TestClient) -> None:
    """path 의 provider 가 enum 외 값이면 422 — FastAPI 가 path validation 처리."""
    res = client.post(
        "/api/v1/auth/social/facebook/callback", json={"code": "x"}
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"
    fields = res.json()["error"]["fields"]
    assert "path.provider" in fields


def test_social_sign_up_rejects_unagreed_terms(client: TestClient) -> None:
    """필수 약관 미동의 → 422 (Pydantic field_validator 단계에서 거절).

    login_id/username 은 더 이상 입력받지 않음 — 서버 자동생성/PG 닉네임 사용.
    """
    res = client.post(
        "/api/v1/auth/social/sign-up",
        json={
            "tempToken": "x" * 20,
            "agreedTerms": False,
            "agreedPrivacy": True,
        },
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"
