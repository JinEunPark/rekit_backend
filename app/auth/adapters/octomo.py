"""Octomo 전화번호 인증(MO 기반, QR 방식) 어댑터. PhoneVerifier Protocol 구현체."""

from __future__ import annotations

import secrets

import httpx
from redis.asyncio import Redis

from app.auth.adapters.ports import PhoneVerificationChallenge
from app.core.config import settings

_OCTOMO_API_BASE = "https://api.octoverse.kr"
_WITHIN_MINUTES = 5  # Octomo 에 "최근 N분 내 수신" 을 묻는 창
# 로컬 코드 TTL 은 withinMinutes 창보다 넉넉히 길게 — 경계(4분 59초)에서 로컬 코드가
# 먼저 만료돼 verify() 가 Octomo 에 물어보지도 못하고 422 로 떨어지는 걸 막는다.
# 시간 유효성 판정의 권한은 Octomo(withinMinutes)에 있고, 로컬은 재사용 방지용 저장일 뿐.
_CODE_TTL_SECONDS = 600
_CODE_KEY = "octomo:phone-code:{}"


class OctomoPhoneVerifier:
    """Octomo REST API 어댑터. PhoneVerifier Protocol 구현체."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def _auth_headers(self) -> dict[str, str]:
        api_key = getattr(settings, "octomo_api_key", "") or ""
        if not api_key:
            raise RuntimeError("OCTOMO_API_KEY 가 설정되지 않았습니다.")
        return {"Content-Type": "application/json", "Authorization": f"Octomo {api_key}"}

    async def issue_challenge(self, phone: str) -> PhoneVerificationChallenge:
        # QR 방식이라 사용자가 직접 타이핑하지 않으므로 16자 hex 로 강화.
        digits = phone.replace("-", "")
        code = secrets.token_hex(8)
        await self._redis.set(_CODE_KEY.format(digits), code, ex=_CODE_TTL_SECONDS)

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{_OCTOMO_API_BASE}/octomo/v1/public/message/qr-code",
                json={"text": code},
                headers=self._auth_headers(),
            )
        # Octomo QR 생성 API 는 성공 시 200 이 아닌 201(Created) 을 반환한다.
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Octomo QR API 오류: {resp.status_code} {resp.text}")

        qr_code = resp.json()["qrCode"]
        return PhoneVerificationChallenge(code=code, qr_code=qr_code)

    async def verify(self, phone: str) -> bool:
        digits = phone.replace("-", "")
        code = await self._redis.get(_CODE_KEY.format(digits))
        if code is None:
            return False  # 발급된 적 없거나 TTL 만료 — Octomo 호출 자체가 무의미

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{_OCTOMO_API_BASE}/octomo/v1/public/message/exists",
                json={"mobileNum": digits, "text": code, "withinMinutes": _WITHIN_MINUTES},
                headers=self._auth_headers(),
            )
        # Octomo exists API 도 성공 시 200 이 아닌 201(Created) 을 반환한다.
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Octomo API 오류: {resp.status_code} {resp.text}")

        exists = bool(resp.json().get("exists"))
        if exists:
            await self._redis.delete(_CODE_KEY.format(digits))  # 재사용 방지
        return exists
