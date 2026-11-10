"""외부 호출 지연 메트릭 `rekle_external_request_duration_seconds{service,operation,outcome}`.

요청 지연이 우리 코드 탓인지 외부(Octomo·SMTP·S3·OAuth·Redis) 탓인지 부하테스트에서
분리해 보려는 용도.
네트워크는 전부 mock/fake — 메트릭은 프로세스 전역이라 전후 차이로 검증한다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from botocore.exceptions import ClientError
from prometheus_client import REGISTRY
from redis.asyncio import Redis

from app.auth.adapters.google_oauth import GoogleOAuthAdapter
from app.auth.adapters.kakao_oauth import KakaoOAuthAdapter
from app.auth.adapters.naver_oauth import NaverOAuthAdapter
from app.common.email.gmail_adapter import GmailSmtpEmailSender
from app.common.storage.s3_adapter import S3StorageAdapter
from app.core.exceptions import SocialOAuthFailedError
from app.core.metrics import observe_external_call
from app.core.redis import InstrumentedRedis, get_redis
from tests.test_octomo_adapter import _make_verifier, _mock_client, _qr_response

_METRIC = "rekle_external_request_duration_seconds_count"


def _count(service: str, operation: str, outcome: str) -> float:
    labels = {"service": service, "operation": operation, "outcome": outcome}
    return REGISTRY.get_sample_value(_METRIC, labels) or 0.0


# ── 공용 헬퍼 ────────────────────────────────────────────────────


def test_observe_external_call_records_error_outcome_and_reraises() -> None:
    """예외가 나가면 outcome=error 로 기록하고 예외는 그대로 전파한다 (삼키지 않음)."""
    before = _count("octomo", "verify", "error")

    with pytest.raises(RuntimeError), observe_external_call("octomo", "verify"):
        raise RuntimeError("boom")

    assert _count("octomo", "verify", "error") == before + 1


def test_observe_external_call_records_ok_outcome_on_success() -> None:
    before = _count("octomo", "verify", "ok")

    with observe_external_call("octomo", "verify"):
        pass

    assert _count("octomo", "verify", "ok") == before + 1


# ── Octomo ──────────────────────────────────────────────────────


async def test_octomo_non_2xx_response_counts_error() -> None:
    """HTTP 응답은 왔어도 오류 status 면 실패 — 전송 성공만으로 ok 로 세지 않는다."""
    verifier, _ = _make_verifier()
    resp = MagicMock(status_code=500, text="server error")
    before = _count("octomo", "issue_challenge", "error")

    with (
        patch("app.auth.adapters.octomo.httpx.AsyncClient", return_value=_mock_client(resp)),
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        pytest.raises(RuntimeError),
    ):
        mock_settings.octomo_api_key = "k"
        await verifier.issue_challenge("010-1234-5678")

    assert _count("octomo", "issue_challenge", "error") == before + 1


async def test_octomo_issue_challenge_counts_ok() -> None:
    verifier, _ = _make_verifier()
    before = _count("octomo", "issue_challenge", "ok")

    with (
        patch(
            "app.auth.adapters.octomo.httpx.AsyncClient",
            return_value=_mock_client(_qr_response()),
        ),
        patch("app.auth.adapters.octomo.settings") as mock_settings,
    ):
        mock_settings.octomo_api_key = "k"
        await verifier.issue_challenge("010-1234-5678")

    assert _count("octomo", "issue_challenge", "ok") == before + 1


# ── SMTP ────────────────────────────────────────────────────────


async def test_smtp_send_failure_counts_error() -> None:
    sender = GmailSmtpEmailSender(user="u@gmail.com", password="p")
    before = _count("smtp", "send", "error")

    with (
        patch("aiosmtplib.send", AsyncMock(side_effect=OSError("conn refused"))),
        pytest.raises(OSError),
    ):
        await sender.send(to="a@example.com", subject="s", body="b")

    assert _count("smtp", "send", "error") == before + 1


async def test_smtp_send_success_counts_ok() -> None:
    sender = GmailSmtpEmailSender(user="u@gmail.com", password="p")
    before = _count("smtp", "send", "ok")

    with patch("aiosmtplib.send", AsyncMock(return_value=({}, "OK"))):
        await sender.send(to="a@example.com", subject="s", body="b")

    assert _count("smtp", "send", "ok") == before + 1


# ── S3 ──────────────────────────────────────────────────────────


def _s3_adapter_with(fake_client: Any) -> S3StorageAdapter:
    adapter = S3StorageAdapter()

    @asynccontextmanager
    async def _client() -> AsyncIterator[Any]:
        yield fake_client

    adapter._client = _client  # type: ignore[method-assign]
    return adapter


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code}}, "HeadObject")


async def test_s3_head_missing_object_counts_ok() -> None:
    """404 는 '없음' 이라는 정상 응답 — 스토리지 장애(error)로 세면 알림이 오탐한다."""
    fake = MagicMock()
    fake.head_object = AsyncMock(side_effect=_client_error("404"))
    before = _count("s3", "head", "ok")

    assert await _s3_adapter_with(fake).head("products/x.png") is None

    assert _count("s3", "head", "ok") == before + 1


async def test_s3_head_server_error_counts_error() -> None:
    fake = MagicMock()
    fake.head_object = AsyncMock(side_effect=_client_error("500"))
    before = _count("s3", "head", "error")

    with pytest.raises(ClientError):
        await _s3_adapter_with(fake).head("products/x.png")

    assert _count("s3", "head", "error") == before + 1


@pytest.mark.parametrize(
    ("operation", "call"),
    [
        ("put_object", lambda a: a.put_object("k", b"x", "image/svg+xml")),
        ("get_object", lambda a: a.get_object("k")),
        ("delete", lambda a: a.delete("k")),
        ("ensure_bucket", lambda a: a.ensure_bucket()),
    ],
)
async def test_s3_network_operations_count_ok(
    operation: str, call: Callable[[S3StorageAdapter], Any]
) -> None:
    fake = MagicMock()
    body = MagicMock()
    body.read = AsyncMock(return_value=b"x")
    fake.get_object = AsyncMock(return_value={"Body": body})
    fake.put_object = AsyncMock()
    fake.delete_object = AsyncMock()
    fake.head_bucket = AsyncMock()
    before = _count("s3", operation, "ok")

    await call(_s3_adapter_with(fake))

    assert _count("s3", operation, "ok") == before + 1


# ── OAuth ───────────────────────────────────────────────────────


def _oauth_cases() -> list[tuple[str, Any, dict[str, Any]]]:
    return [
        (
            "kakao",
            KakaoOAuthAdapter(client_id="i", client_secret=None, redirect_uri="https://x/cb"),
            {"id": 1, "kakao_account": {"email": "a@example.com"}},
        ),
        (
            "naver",
            NaverOAuthAdapter(client_id="i", client_secret="s", redirect_uri="https://x/cb"),
            {"resultcode": "00", "response": {"id": "n1", "email": "a@example.com"}},
        ),
        (
            "google",
            GoogleOAuthAdapter(client_id="i", client_secret="s", redirect_uri="https://x/cb"),
            {"sub": "g1", "email": "a@example.com", "email_verified": True},
        ),
    ]


def _patch_httpx(provider: str, handler: Callable[[httpx.Request], httpx.Response]) -> Any:
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    return patch(
        f"app.auth.adapters.{provider}_oauth.httpx.AsyncClient",
        lambda **kw: real_client(transport=transport, **kw),
    )


@pytest.mark.parametrize(("provider", "adapter", "profile"), _oauth_cases())
async def test_oauth_exchange_counts_token_and_profile_ok(
    provider: str, adapter: Any, profile: dict[str, Any]
) -> None:
    """토큰 교환·프로필 조회는 호출 대상 서버가 달라 operation 을 나눠 기록한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization"):
            return httpx.Response(200, json=profile)
        return httpx.Response(200, json={"access_token": "t"})

    before_token = _count(provider, "token", "ok")
    before_profile = _count(provider, "profile", "ok")

    with _patch_httpx(provider, handler):
        await adapter.exchange_code("code", state="st")

    assert _count(provider, "token", "ok") == before_token + 1
    assert _count(provider, "profile", "ok") == before_profile + 1


@pytest.mark.parametrize(("provider", "adapter", "profile"), _oauth_cases())
async def test_oauth_token_rejected_counts_error(
    provider: str, adapter: Any, profile: dict[str, Any]
) -> None:
    before = _count(provider, "token", "error")

    with (
        _patch_httpx(provider, lambda _req: httpx.Response(400, json={"error": "bad"})),
        pytest.raises(SocialOAuthFailedError),
    ):
        await adapter.exchange_code("code", state="st")

    assert _count(provider, "token", "error") == before + 1


# ── Redis ───────────────────────────────────────────────────────


def test_get_redis_returns_instrumented_client() -> None:
    """앱의 모든 Redis 명령은 get_redis() 싱글턴을 거친다 — 여기만 계측하면 전부 잡힌다."""
    assert isinstance(get_redis(), InstrumentedRedis)


async def test_redis_command_counts_ok_by_command_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """operation 은 명령 이름(소문자) — 앱이 쓰는 명령 종류가 손에 꼽혀 카디널리티가 작다."""
    monkeypatch.setattr(Redis, "execute_command", AsyncMock(return_value="OK"))
    before = _count("redis", "set", "ok")

    await InstrumentedRedis().set("k", "v", ex=60)

    assert _count("redis", "set", "ok") == before + 1


async def test_redis_command_failure_counts_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from redis.exceptions import TimeoutError as RedisTimeoutError

    monkeypatch.setattr(
        Redis, "execute_command", AsyncMock(side_effect=RedisTimeoutError("timeout"))
    )
    before = _count("redis", "get", "error")

    with pytest.raises(RedisTimeoutError):
        await InstrumentedRedis().get("k")

    assert _count("redis", "get", "error") == before + 1
