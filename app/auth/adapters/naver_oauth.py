"""Naver OAuth 어댑터.

- token exchange : POST https://nid.naver.com/oauth2.0/token (state 필수)
- user info      : GET  https://openapi.naver.com/v1/nid/me

응답 구조:
  /v1/nid/me → { resultcode: "00", message: "success", response: {id, email, name, ...} }
  resultcode != "00" 이면 토큰이 만료/위조된 경우 — RuntimeError raise.
"""

from __future__ import annotations

import httpx

from app.auth.adapters.ports import SocialProfile

_TOKEN_URL = "https://nid.naver.com/oauth2.0/token"
_USER_INFO_URL = "https://openapi.naver.com/v1/nid/me"


class NaverOAuthAdapter:
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
        if not state:
            raise ValueError("Naver OAuth 는 token exchange 시 state 가 필수입니다.")

        async with httpx.AsyncClient(timeout=10.0) as client:
            access_token = await self._fetch_access_token(client, code, state)
            return await self._fetch_profile(client, access_token)

    async def _fetch_access_token(
        self, client: httpx.AsyncClient, code: str, state: str
    ) -> str:
        params = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "state": state,
        }
        res = await client.get(_TOKEN_URL, params=params)
        res.raise_for_status()
        return res.json()["access_token"]

    async def _fetch_profile(self, client: httpx.AsyncClient, access_token: str) -> SocialProfile:
        res = await client.get(
            _USER_INFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        res.raise_for_status()
        body = res.json()

        if body.get("resultcode") != "00":
            raise RuntimeError(f"Naver user info failed: {body.get('message')}")

        profile = body.get("response") or {}
        email = profile.get("email")
        return SocialProfile(
            provider="naver",
            social_id=str(profile["id"]),
            email=email.lower() if email else None,
            name=profile.get("name") or profile.get("nickname"),
        )
