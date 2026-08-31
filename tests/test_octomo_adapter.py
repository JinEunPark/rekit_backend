"""OctomoPhoneVerifier 어댑터 단위 테스트.

실제 네트워크 호출 없이 httpx.AsyncClient를 mock으로 교체하여 검증.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.auth.adapters.octomo import OctomoPhoneVerifier


class _FakeRedis:
    """dict 기반 인메모리 Redis stub."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self.ex: dict[str, int | None] = {}

    async def set(self, key: str, value: str, *, ex: int | None = None) -> str:
        self._store[key] = value
        self.ex[key] = ex
        return "OK"

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, key: str) -> int:
        return (self._store.pop(key, None) and 1) or 0


def _make_verifier() -> tuple[OctomoPhoneVerifier, _FakeRedis]:
    redis = _FakeRedis()
    return OctomoPhoneVerifier(redis), redis  # type: ignore[arg-type]


def _mock_client(resp: MagicMock) -> AsyncMock:
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=resp)
    return client


def _qr_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"qrCode": "data:image/png;base64,abc123"}
    return resp


def _exists_response(exists: bool) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"exists": exists}
    return resp


# ── issue_challenge ──────────────────────────────────────────────────────────


async def test_issue_challenge_generates_16_char_hex_code() -> None:
    """secrets.token_hex(8) 이므로 16자 hex 문자열이 생성된다."""
    verifier, redis = _make_verifier()
    client = _mock_client(_qr_response())

    with (
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
    ):
        mock_settings.octomo_api_key = "test_key"
        challenge = await verifier.issue_challenge("01012345678")

    assert len(challenge.code) == 16
    assert all(c in "0123456789abcdef" for c in challenge.code)
    stored = await redis.get("octomo:phone-code:01012345678")
    assert stored == challenge.code


async def test_issue_challenge_code_ttl_outlives_octomo_within_minutes_window() -> None:
    """Redis 코드 TTL 은 Octomo withinMinutes 창보다 길어야 한다.

    (회귀: 둘이 정확히 5분으로 같아서, 사용자가 4분 59초에 문자를 보내면 Octomo
    쪽에선 아직 유효한데 로컬 코드가 먼저 만료돼 verify() 가 무조건 422 로 떨어짐.
    시간 판정의 권한은 Octomo 에 있어야 하고, 로컬 TTL 은 그보다 여유를 둔다.)
    """
    from app.auth.adapters.octomo import _WITHIN_MINUTES

    verifier, redis = _make_verifier()
    client = _mock_client(_qr_response())

    with (
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
    ):
        mock_settings.octomo_api_key = "test_key"
        await verifier.issue_challenge("01012345678")

    ttl = redis.ex["octomo:phone-code:01012345678"]
    assert ttl is not None and ttl > _WITHIN_MINUTES * 60


async def test_issue_challenge_hyphenated_phone_uses_digit_only_redis_key() -> None:
    """휴대폰 번호가 010-1234-5678 형식으로 저장돼 있어도 Redis 키는 숫자만 사용한다."""
    verifier, redis = _make_verifier()
    client = _mock_client(_qr_response())

    with (
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
    ):
        mock_settings.octomo_api_key = "test_key"
        challenge = await verifier.issue_challenge("010-1234-5678")

    stored = await redis.get("octomo:phone-code:01012345678")
    assert stored == challenge.code


async def test_issue_challenge_calls_qr_code_api_with_code_as_text() -> None:
    """QR 발급 요청 바디의 text 가 발급된 code 와 정확히 일치한다."""
    verifier, _ = _make_verifier()
    client = _mock_client(_qr_response())

    with (
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
    ):
        mock_settings.octomo_api_key = "test_key"
        challenge = await verifier.issue_challenge("01012345678")

    call_kwargs = client.post.call_args.kwargs
    assert call_kwargs["json"] == {"text": challenge.code}
    assert call_kwargs["headers"]["Authorization"] == "Octomo test_key"


async def test_issue_challenge_returns_qr_code_from_response() -> None:
    """Octomo 응답의 qrCode 값을 그대로 반환한다."""
    verifier, _ = _make_verifier()
    client = _mock_client(_qr_response())

    with (
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
    ):
        mock_settings.octomo_api_key = "test_key"
        challenge = await verifier.issue_challenge("01012345678")

    assert challenge.qr_code == "data:image/png;base64,abc123"


async def test_issue_challenge_no_api_key_raises_runtime_error() -> None:
    """OCTOMO_API_KEY 가 없으면 RuntimeError."""
    verifier, _ = _make_verifier()

    with patch("app.auth.adapters.octomo.settings") as mock_settings:
        mock_settings.octomo_api_key = None
        with pytest.raises(RuntimeError):
            await verifier.issue_challenge("01012345678")


async def test_issue_challenge_non_200_raises_runtime_error() -> None:
    """QR API 가 200/201 이 아니면 RuntimeError."""
    verifier, _ = _make_verifier()
    resp = MagicMock()
    resp.status_code = 400
    resp.text = "bad request"
    client = _mock_client(resp)

    with (
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
    ):
        mock_settings.octomo_api_key = "test_key"
        with pytest.raises(RuntimeError):
            await verifier.issue_challenge("01012345678")


async def test_issue_challenge_201_returns_qr_code() -> None:
    """Octomo QR API 는 성공 시 200 이 아닌 201(Created) 을 반환한다 — 정상 처리돼야 한다."""
    verifier, _ = _make_verifier()
    resp = MagicMock()
    resp.status_code = 201
    resp.json.return_value = {"qrCode": "data:image/png;base64,abc123"}
    client = _mock_client(resp)

    with (
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
    ):
        mock_settings.octomo_api_key = "test_key"
        challenge = await verifier.issue_challenge("01012345678")

    assert challenge.qr_code == "data:image/png;base64,abc123"


# ── verify ───────────────────────────────────────────────────────────────────


async def test_verify_with_stored_code_calls_octomo_exists_and_returns_true() -> None:
    """저장된 코드로 Octomo exists 를 조회하고 exists=true 면 True 반환."""
    verifier, redis = _make_verifier()
    await redis.set("octomo:phone-code:01012345678", "abc123def4567890")
    client = _mock_client(_exists_response(True))

    with (
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
    ):
        mock_settings.octomo_api_key = "test_key"
        result = await verifier.verify("01012345678")

    assert result is True
    call_kwargs = client.post.call_args.kwargs
    assert call_kwargs["json"] == {
        "mobileNum": "01012345678",
        "text": "abc123def4567890",
        "withinMinutes": 5,
    }


async def test_verify_hyphenated_phone_sends_digit_only_mobile_num() -> None:
    """휴대폰 번호가 010-1234-5678 형식이어도 Octomo 에는 숫자만 전달한다."""
    verifier, redis = _make_verifier()
    await redis.set("octomo:phone-code:01012345678", "abc123def4567890")
    client = _mock_client(_exists_response(True))

    with (
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
    ):
        mock_settings.octomo_api_key = "test_key"
        result = await verifier.verify("010-1234-5678")

    assert result is True
    call_kwargs = client.post.call_args.kwargs
    assert call_kwargs["json"]["mobileNum"] == "01012345678"


async def test_verify_no_stored_code_does_not_call_octomo_api() -> None:
    """Redis 에 코드가 없으면(미발급/만료) Octomo API 호출 없이 False."""
    verifier, _ = _make_verifier()
    client = _mock_client(_exists_response(True))

    with (
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
    ):
        mock_settings.octomo_api_key = "test_key"
        result = await verifier.verify("01099998888")

    assert result is False
    client.post.assert_not_called()


async def test_verify_non_200_raises_runtime_error() -> None:
    """exists API 가 200/201 이 아니면 RuntimeError."""
    verifier, redis = _make_verifier()
    await redis.set("octomo:phone-code:01012345678", "abc123def4567890")
    resp = MagicMock()
    resp.status_code = 500
    resp.text = "server error"
    client = _mock_client(resp)

    with (
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
    ):
        mock_settings.octomo_api_key = "test_key"
        with pytest.raises(RuntimeError):
            await verifier.verify("01012345678")


async def test_verify_201_returns_true() -> None:
    """Octomo exists API 도 성공 시 200 이 아닌 201(Created) 을 반환할 수 있다."""
    verifier, redis = _make_verifier()
    await redis.set("octomo:phone-code:01012345678", "abc123def4567890")
    resp = MagicMock()
    resp.status_code = 201
    resp.json.return_value = {"exists": True}
    client = _mock_client(resp)

    with (
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
    ):
        mock_settings.octomo_api_key = "test_key"
        result = await verifier.verify("01012345678")

    assert result is True


async def test_verify_octomo_returns_false_when_message_not_found() -> None:
    """Octomo 가 exists=false 를 반환하면 False, Redis 키는 그대로 남는다."""
    verifier, redis = _make_verifier()
    await redis.set("octomo:phone-code:01012345678", "abc123def4567890")
    client = _mock_client(_exists_response(False))

    with (
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
    ):
        mock_settings.octomo_api_key = "test_key"
        result = await verifier.verify("01012345678")

    assert result is False
    assert await redis.get("octomo:phone-code:01012345678") == "abc123def4567890"


async def test_verify_success_deletes_code_from_redis() -> None:
    """검증 성공 후 Redis 키가 삭제된다 — 재사용/재검증 방지."""
    verifier, redis = _make_verifier()
    await redis.set("octomo:phone-code:01012345678", "abc123def4567890")
    client = _mock_client(_exists_response(True))

    with (
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
    ):
        mock_settings.octomo_api_key = "test_key"
        await verifier.verify("01012345678")

    assert await redis.get("octomo:phone-code:01012345678") is None


async def test_verify_hyphenated_phone_success_deletes_digit_only_redis_key() -> None:
    """휴대폰 번호가 010-1234-5678 형식으로 들어와도 발급 시 쓴 숫자 전용 키가 삭제된다."""
    verifier, redis = _make_verifier()
    await redis.set("octomo:phone-code:01012345678", "abc123def4567890")
    client = _mock_client(_exists_response(True))

    with (
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
    ):
        mock_settings.octomo_api_key = "test_key"
        await verifier.verify("010-1234-5678")

    assert await redis.get("octomo:phone-code:01012345678") is None


async def test_verify_no_api_key_raises_runtime_error() -> None:
    """코드는 있지만 API 키가 없으면 RuntimeError."""
    verifier, redis = _make_verifier()
    await redis.set("octomo:phone-code:01012345678", "abc123def4567890")

    with patch("app.auth.adapters.octomo.settings") as mock_settings:
        mock_settings.octomo_api_key = None
        with pytest.raises(RuntimeError):
            await verifier.verify("01012345678")
