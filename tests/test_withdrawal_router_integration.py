"""소셜 전용 계정 탈퇴 라우터 통합 테스트 — DB 없이 라우팅 배선만 확인.

reauth-for-withdrawal → DELETE /users/me 두 엔드포인트를 이어 붙인 전체 플로우가
라우터 레이어에서 올바르게 배선돼 있는지 검증한다 (path/인증가드/스키마 매핑).

service 도메인 로직(social_id 매칭, has_password 분기, 토큰 sub 검증)은
test_social_login.py / test_user_service.py 에서 이미 fake repo 로 검증 완료 —
여기는 실제 카카오/네이버/구글 OAuth 동의 화면을 타는 부분만 빼고, 그 앞뒤
(auth guard 통과 → 요청 스키마 매핑 → 응답 스키마) 가 맞물리는지 확인한다.

실제 PG 동의 화면을 사람이 클릭해서 code 를 받아오는 구간은 이 테스트로도,
다른 자동화로도 대체 불가 — 실 계정으로 종단 확인이 별도로 필요하다.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth.adapters.ports import SocialProfile
from app.auth.auth_service import AuthService
from app.core.deps import get_active_user, get_auth_service, get_oauth_provider, get_user_service
from app.core.security import decode_withdrawal_token
from app.main import app
from tests.conftest import make_user


class _FakeOAuth:
    def __init__(self, profile: SocialProfile) -> None:
        self.profile = profile

    async def exchange_code(self, code: str, state: str | None = None) -> SocialProfile:
        return self.profile


class _FakeAuthRepoForReauth:
    """get_social_account 만 필요 — 로그인된 본인과 연결된 SocialAccount 하나만 둔다."""

    def __init__(self, *, user_id: int, provider: str, social_id: str) -> None:
        self._user_id = user_id
        self._provider = provider
        self._social_id = social_id

    async def get_social_account(self, provider: object, social_id: str) -> object | None:
        if str(provider) != self._provider or social_id != self._social_id:
            return None

        class _Row:
            user_id = self._user_id

        return _Row()


class _FakeUserService:
    def __init__(self) -> None:
        self.withdraw_calls: list[dict[str, str | None]] = []

    async def withdraw(
        self, *, user: object, password: str | None = None, withdrawal_token: str | None = None
    ) -> None:
        self.withdraw_calls.append({"password": password, "withdrawal_token": withdrawal_token})


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_reauth_then_withdraw_full_router_flow(client: TestClient) -> None:
    """has_password=False 유저가 reauth 로 토큰 받아 DELETE /users/me 까지 성공."""
    social_user = make_user(user_id=42, has_password=False)
    app.dependency_overrides[get_active_user] = lambda: social_user

    profile = SocialProfile(
        provider="kakao", social_id="kakao-real-42", email=social_user.email, name="이름"
    )
    app.dependency_overrides[get_oauth_provider] = lambda provider: _FakeOAuth(profile)

    fake_repo = _FakeAuthRepoForReauth(
        user_id=social_user.id, provider="kakao", social_id="kakao-real-42"
    )
    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        fake_repo, email_sender=None, redis=None  # type: ignore[arg-type]
    )

    reauth_res = client.post(
        "/api/v1/auth/social/kakao/reauth-for-withdrawal", json={"code": "abc"}
    )
    assert reauth_res.status_code == 200
    token = reauth_res.json()["withdrawalToken"]
    assert int(decode_withdrawal_token(token)["sub"]) == social_user.id

    fake_user_service = _FakeUserService()
    app.dependency_overrides[get_user_service] = lambda: fake_user_service

    delete_res = client.request(
        "DELETE", "/api/v1/users/me", json={"withdrawalToken": token}
    )
    assert delete_res.status_code == 204
    assert fake_user_service.withdraw_calls == [
        {"password": None, "withdrawal_token": token}
    ]


def test_reauth_rejects_when_social_account_belongs_to_someone_else(
    client: TestClient,
) -> None:
    """로그인된 사용자와 다른 소셜 계정으로 재인증 시도 → 401."""
    social_user = make_user(user_id=42, has_password=False)
    app.dependency_overrides[get_active_user] = lambda: social_user

    profile = SocialProfile(
        provider="kakao", social_id="belongs-to-other", email="other@example.com", name=None
    )
    app.dependency_overrides[get_oauth_provider] = lambda provider: _FakeOAuth(profile)

    fake_repo = _FakeAuthRepoForReauth(
        user_id=999, provider="kakao", social_id="belongs-to-other"
    )
    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        fake_repo, email_sender=None, redis=None  # type: ignore[arg-type]
    )

    res = client.post("/api/v1/auth/social/kakao/reauth-for-withdrawal", json={"code": "abc"})
    assert res.status_code == 401


def test_reauth_for_withdrawal_requires_auth(client: TestClient) -> None:
    """로그인 안 된 상태 — get_active_user override 없이 호출하면 401/403."""
    res = client.post("/api/v1/auth/social/kakao/reauth-for-withdrawal", json={"code": "abc"})
    assert res.status_code in (401, 403)
