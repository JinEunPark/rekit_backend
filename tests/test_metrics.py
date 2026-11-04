"""app.core.metrics — Prometheus 메트릭 노출·HTTP 계측·DB 풀 계측.

메트릭은 프로세스 전역이라 다른 테스트가 먼저 값을 올렸을 수 있다 — 절대값이 아니라
전후 차이로 검증한다.
"""

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from prometheus_client import REGISTRY

from app.core import metrics
from app.main import app


def _sample(name: str, labels: dict[str, str] | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


@pytest.fixture
def client() -> Iterator[httpx.AsyncClient]:
    yield httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_http_metrics_skip_health_and_metrics_paths(client: httpx.AsyncClient) -> None:
    """헬스체크·Prometheus 수집 자체는 트래픽으로 세지 않는다 (RPS 왜곡 방지)."""
    health = {"method": "GET", "path": "/health", "status": "200"}
    scrape = {"method": "GET", "path": "/metrics", "status": "200"}
    before_health = _sample("rekle_http_requests_total", health)
    before_scrape = _sample("rekle_http_requests_total", scrape)

    await client.get("/health")
    await client.get("/metrics")

    assert _sample("rekle_http_requests_total", health) == before_health
    assert _sample("rekle_http_requests_total", scrape) == before_scrape


async def test_http_metrics_label_unmatched_path_as_placeholder(client: httpx.AsyncClient) -> None:
    """라우트가 없는 경로는 원문 대신 고정 라벨 — 스캐너의 무작위 경로로 시계열 폭발 방지."""
    labels = {"method": "GET", "path": "<unmatched>", "status": "404"}
    before = _sample("rekle_http_requests_total", labels)

    await client.get("/wp-admin/random-scan-path")

    assert _sample("rekle_http_requests_total", labels) == before + 1


async def test_http_metrics_count_request_with_full_route_template(
    client: httpx.AsyncClient,
) -> None:
    """요청 수는 실제 경로가 아닌 전체 라우트 템플릿(/api/v1 포함) + 상태 코드로 센다."""
    labels = {"method": "GET", "path": "/api/v1/orders/{order_number}", "status": "401"}
    before = _sample("rekle_http_requests_total", labels)

    await client.get("/api/v1/orders/RK-2611050001")

    assert _sample("rekle_http_requests_total", labels) == before + 1


async def test_http_metrics_observe_request_duration(client: httpx.AsyncClient) -> None:
    """응답시간 Histogram 에 관측치가 쌓인다 (p95 계산용)."""
    labels = {"method": "GET", "path": "/api/v1/orders/{order_number}"}
    before = _sample("rekle_http_request_duration_seconds_count", labels)

    await client.get("/api/v1/orders/RK-2611050002")

    assert _sample("rekle_http_request_duration_seconds_count", labels) == before + 1


async def test_http_in_progress_gauge_returns_to_previous_after_request(
    client: httpx.AsyncClient,
) -> None:
    """처리 중 요청 수는 요청이 끝나면 원래대로 돌아온다 (inc/dec 짝)."""
    before = _sample("rekle_http_requests_in_progress")

    await client.get("/api/v1/orders/RK-2611050003")

    assert _sample("rekle_http_requests_in_progress") == before


async def test_metrics_endpoint_serves_prometheus_text_format(client: httpx.AsyncClient) -> None:
    """/metrics 는 Prometheus text format 으로 HTTP·비즈니스 메트릭을 노출한다."""
    await client.get("/api/v1/orders/RK-2611050004")

    res = await client.get("/metrics")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert "rekle_http_requests_total" in res.text
    assert "rekle_payment_confirm_total" in res.text


async def test_metrics_endpoint_is_hidden_from_openapi() -> None:
    """/metrics 는 API 문서에 노출하지 않는다."""
    assert "/metrics" not in app.openapi()["paths"]


def test_render_latest_aggregates_worker_files_in_multiprocess_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PROMETHEUS_MULTIPROC_DIR 가 있으면 워커별 파일을 합산하는 레지스트리로 렌더한다.

    gunicorn -w 4 운영 구성.

    빈 디렉터리면 합산할 값이 없으니 단일 프로세스 메트릭(rekle_*)이 섞여 나오지 않아야 한다.
    """
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))

    body = metrics.render_latest()

    assert b"rekle_http_requests_total" not in body


def test_render_latest_uses_process_registry_without_multiprocess_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """로컬 uvicorn 처럼 단일 프로세스면 기본 레지스트리를 그대로 렌더한다."""
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)

    body = metrics.render_latest()

    assert b"rekle_http_requests_total" in body


async def test_db_pool_gauge_tracks_checkout_and_checkin() -> None:
    """DB 커넥션 대여 중엔 사용 중 커넥션 Gauge 가 1 오르고, 반납하면 돌아온다 (pool 고갈 감시).

    전역 engine 은 앞선 테스트의 이벤트 루프에서 만든 커넥션을 풀에 들고 있어 재사용하면
    "attached to a different loop" — 이 테스트 전용 엔진에 같은 계측을 붙여 검증한다.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    test_engine = create_async_engine(settings.database_url)
    metrics.instrument_pool(test_engine.sync_engine.pool)
    before = _sample("rekle_db_pool_connections_in_use")
    try:
        async with test_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            during = _sample("rekle_db_pool_connections_in_use")
    finally:
        await test_engine.dispose()

    assert during == before + 1
    assert _sample("rekle_db_pool_connections_in_use") == before


async def test_app_engine_pool_stays_instrumented_after_dispose() -> None:
    """앱 전역 engine 의 풀도 계측된다 — dispose 로 풀이 새로 만들어져도 계측이 유지된다.

    dispose 는 다른 테스트·lifespan 종료에서도 일어난다.
    앞선 테스트 루프의 커넥션을 비우는 효과도 있다.
    """
    from sqlalchemy import text

    from app.core.database import engine

    await engine.dispose()
    before = _sample("rekle_db_pool_connections_in_use")

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
        during = _sample("rekle_db_pool_connections_in_use")
    await engine.dispose()

    assert during == before + 1
    assert _sample("rekle_db_pool_connections_in_use") == before
