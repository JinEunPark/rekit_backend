"""헬스체크 — /health(liveness) 와 /health/ready(readiness: DB·Redis).

liveness 는 의존성을 보지 않는다 — DB 장애 때 컨테이너 재시작이 반복되는 걸 막기 위해.
readiness 는 외부 업타임 모니터가 "실제로 요청을 처리할 수 있는지" 보는 용도.
"""

import asyncio
from collections.abc import Iterator

import httpx
import pytest

from app.core.health import get_readiness_checks, run_checks
from app.main import app


async def _ok() -> None:
    return None


async def _boom() -> None:
    raise ConnectionError("connection refused")


async def _hang() -> None:
    await asyncio.sleep(10)


async def test_run_checks_reports_ok_for_every_passing_check() -> None:
    results = await run_checks({"database": _ok, "redis": _ok}, timeout=1)

    assert results == {"database": "ok", "redis": "ok"}


async def test_run_checks_isolates_failing_check() -> None:
    """하나가 실패해도 나머지는 계속 확인해 어느 의존성이 문제인지 알려준다."""
    results = await run_checks({"database": _boom, "redis": _ok}, timeout=1)

    assert results == {"database": "fail", "redis": "ok"}


async def test_run_checks_marks_slow_check_as_timeout() -> None:
    """응답 없는 의존성이 헬스체크 전체를 붙잡지 않게 타임아웃으로 끊는다."""
    results = await run_checks({"redis": _hang}, timeout=0.05)

    assert results == {"redis": "timeout"}


@pytest.fixture
def client() -> Iterator[httpx.AsyncClient]:
    yield httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


async def test_ready_returns_503_with_failed_dependency_name(client: httpx.AsyncClient) -> None:
    app.dependency_overrides[get_readiness_checks] = lambda: {"database": _boom, "redis": _ok}

    res = await client.get("/health/ready")

    assert res.status_code == 503
    assert res.json() == {"status": "unavailable", "checks": {"database": "fail", "redis": "ok"}}


async def test_ready_returns_200_when_real_database_and_redis_respond(
    client: httpx.AsyncClient,
) -> None:
    """로컬 인프라(postgres·redis 컨테이너) 대상 — 실제 SELECT 1 / PING."""
    res = await client.get("/health/ready")

    assert res.status_code == 200
    assert res.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


async def test_liveness_does_not_touch_dependencies(client: httpx.AsyncClient) -> None:
    """의존성이 죽어도 /health 는 200 — 프로세스가 살아 있으면 재시작하지 않는다."""
    app.dependency_overrides[get_readiness_checks] = lambda: {"database": _boom}

    res = await client.get("/health")

    assert res.status_code == 200


async def test_ready_is_hidden_from_openapi() -> None:
    assert "/health/ready" not in app.openapi()["paths"]
