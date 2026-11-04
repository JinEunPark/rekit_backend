"""app.core.sentry — 에러 추적 초기화와 전송 전 필터.

DSN 이 없으면 아무것도 하지 않는다(로컬·테스트 기본). 실제 전송은 하지 않고
init 인자와 before_send 동작만 검증한다.
"""

from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk
import structlog

from app.core import sentry
from app.core.exceptions import OrderNotFoundError


@pytest.fixture(autouse=True)
def _clear_context() -> Iterator[None]:
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


def _capture_init(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: captured.update(kwargs))
    return captured


@pytest.mark.parametrize("dsn", [None, ""])
def test_init_sentry_is_noop_without_dsn(dsn: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    """DSN 미설정이면 초기화하지 않는다 — 로컬·테스트에서 이벤트가 나가지 않게."""
    captured = _capture_init(monkeypatch)

    enabled = sentry.init_sentry(
        dsn=dsn, environment="development", release="dev", traces_sample_rate=0.0
    )

    assert enabled is False
    assert captured == {}


def test_init_sentry_tags_release_and_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """release=배포 이미지 태그 → 어느 배포부터 에러가 시작됐는지 추적."""
    captured = _capture_init(monkeypatch)

    enabled = sentry.init_sentry(
        dsn="https://key@o0.ingest.sentry.io/0",
        environment="production",
        release="0.0.5",
        traces_sample_rate=0.0,
    )

    assert enabled is True
    assert captured["release"] == "0.0.5"
    assert captured["environment"] == "production"
    assert captured["send_default_pii"] is False


def test_init_sentry_scrubs_project_sensitive_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sentry 기본 목록(password·token…)에 더해 결제키·연락처·CI/DI 도 지운다.

    로그 마스킹과 같은 기준.
    """
    captured = _capture_init(monkeypatch)

    sentry.init_sentry(
        dsn="https://key@o0.ingest.sentry.io/0",
        environment="production",
        release="x",
        traces_sample_rate=0.0,
    )

    denylist = captured["event_scrubber"].denylist
    for key in ("password", "authorization", "payment_key", "phone", "email", "ci", "di"):
        assert key in denylist


def test_before_send_drops_business_error() -> None:
    """정상적인 4xx 거절(BusinessError)은 이슈로 쌓지 않는다."""
    event: dict[str, Any] = {"message": "x"}

    result = sentry.before_send(
        event, {"exc_info": (OrderNotFoundError, OrderNotFoundError(), None)}
    )

    assert result is None


def test_before_send_tags_request_id_and_user_from_log_context() -> None:
    """로그와 같은 request_id·user_id 를 붙여 Sentry 이슈 ↔ 로그를 서로 찾을 수 있게."""
    structlog.contextvars.bind_contextvars(request_id="req-sentry-1", user_id=42)
    event: dict[str, Any] = {"message": "boom"}

    result = sentry.before_send(event, {"exc_info": (RuntimeError, RuntimeError("boom"), None)})

    assert result is not None
    assert result["tags"]["request_id"] == "req-sentry-1"
    assert result["user"] == {"id": "42"}


def test_before_send_keeps_event_without_request_context() -> None:
    """요청 밖(스위퍼 등)의 에러도 그대로 보낸다."""
    event: dict[str, Any] = {"message": "sweeper failed"}

    result = sentry.before_send(event, {})

    assert result == {"message": "sweeper failed"}
