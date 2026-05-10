"""Google OAuth 어댑터.

- token exchange : POST https://oauth2.googleapis.com/token
- user info      : GET  https://www.googleapis.com/oauth2/v3/userinfo

userinfo response: { sub, email, email_verified, name, picture, ... }
- `sub` 는 구글 사용자 고유 ID (string).
- `email_verified` 가 false 면 미인증 — service 측에서 거부 처리.

scope 는 `openid email profile` 권장 (프론트가 요청 시 지정).
"""

from __future__ import annotations

import logging

import httpx

from app.auth.adapters._oauth_helpers import translate_oauth_error
from app.auth.adapters.ports import SocialProfile

_log = logging.getLogger(__name__)

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USER_INFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


class GoogleOAuthAdapter:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    async def exchange_code(self, code: str, state: str | None = None) -> SocialProfile:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                access_token = await self._fetch_access_token(client, code)
                return await self._fetch_profile(client, access_token)
        except httpx.HTTPError as e:
            raise translate_oauth_error(e, provider="google") from e

    async def _fetch_access_token(self, client: httpx.AsyncClient, code: str) -> str:
        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "code": code,
        }
        res = await client.post(_TOKEN_URL, data=data)
        if res.is_error:
            _log.error(
                "Google token exchange failed: %d — %s (redirect_uri=%s)",
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

        # email_verified=False 인 구글 계정 (드물지만 가능) 은 신뢰 불가 — None 처리.
        email: str | None = body.get("email") if body.get("email_verified") else None

        return SocialProfile(
            provider="google",
            social_id=str(body["sub"]),
            email=email.lower() if email else None,
            name=body.get("name"),
        )
