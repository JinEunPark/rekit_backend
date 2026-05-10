"""Kakao OAuth 어댑터.

- token exchange : POST https://kauth.kakao.com/oauth/token
- user info      : GET  https://kapi.kakao.com/v2/user/me

이메일은 카카오 비즈니스 채널 / 사용자 동의 항목에서 "이메일" 을 활성화해야 받음.
미수신 시 SocialProfile.email = None 로 service 가 거부 처리.
"""

from __future__ import annotations

import logging

import httpx

from app.auth.adapters._oauth_helpers import translate_oauth_error
from app.auth.adapters.ports import SocialProfile

_log = logging.getLogger(__name__)

_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
_USER_INFO_URL = "https://kapi.kakao.com/v2/user/me"


class KakaoOAuthAdapter:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str | None,
        redirect_uri: str,
    ) -> None:
        self.client_id = client_id
        # Kakao 는 client_secret 옵션 (콘솔에서 ON 설정 안 했으면 None 가능)
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    async def exchange_code(self, code: str, state: str | None = None) -> SocialProfile:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                access_token = await self._fetch_access_token(client, code)
                return await self._fetch_profile(client, access_token)
        except httpx.HTTPError as e:
            raise translate_oauth_error(e, provider="kakao") from e

    async def _fetch_access_token(self, client: httpx.AsyncClient, code: str) -> str:
        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "code": code,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret

        res = await client.post(_TOKEN_URL, data=data)
        if res.is_error:
            # 카카오는 4xx 시 {error, error_description, error_code} 를 본문으로 보냄.
            # 사용자에게 노출은 위험하니 로그로만 — 디버깅 결정타가 됨.
            _log.error(
                "Kakao token exchange failed: %d — %s (redirect_uri=%s)",
                res.status_code,
                res.text,
                self.redirect_uri,
            )
            res.raise_for_status()
        return res.json()["access_token"]

    async def _fetch_profile(self, client: httpx.AsyncClient, access_token: str) -> SocialProfile:
        res = await client.get(
            _USER_INFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        res.raise_for_status()
        body = res.json()

        social_id = str(body["id"])  # kakao 의 id 는 long, string 으로 통일
        kakao_account = body.get("kakao_account") or {}
        email: str | None = kakao_account.get("email") if kakao_account.get("email_valid", True) else None
        profile = kakao_account.get("profile") or {}
        name: str | None = profile.get("nickname")

        return SocialProfile(
            provider="kakao",
            social_id=social_id,
            email=email.lower() if email else None,
            name=name,
        )
