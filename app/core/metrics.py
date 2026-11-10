"""Prometheus 메트릭 — 정의는 이 파일 한 곳, 미들웨어·서비스·어댑터는 import 해서 기록만 한다.

Spring 의 Micrometer 대응. `prometheus_client` import 를 여기로 모아 두면 나중에
OpenTelemetry 등으로 바꿀 때 이 파일만 고치면 된다.

라벨에는 값의 종류가 손에 꼽히는 것만 넣는다 — user_id·order_number 같은 고유값은
시계열을 폭발시키므로 로그로 남긴다.

gunicorn 은 워커마다 메모리가 분리돼 있어, PROMETHEUS_MULTIPROC_DIR(gunicorn.conf.py 가
설정)가 있으면 워커별 파일을 합산해 노출한다. 로컬 uvicorn 은 단일 프로세스 레지스트리.
"""

import os
import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)
from sqlalchemy import event
from sqlalchemy import exc as sa_exc
from sqlalchemy.pool import AsyncAdaptedQueuePool, Pool, PoolProxiedConnection

__all__ = [
    "CONTENT_TYPE_LATEST",
    "InstrumentedAsyncAdaptedQueuePool",
    "instrument_pool",
    "render_latest",
]

# 응답시간 구간 — SLO(조회 p95 300ms, 결제 1s) 근처를 촘촘하게. 기본 구간은 p95 가 부정확
_HTTP_LATENCY_BUCKETS = (0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 2.0, 5.0)
_PG_LATENCY_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)
# 풀 대기 — 정상은 ms 미만, 고갈 시 pool_timeout(기본 5초)까지 늘어난다
_POOL_WAIT_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
# 루프 지연 — 수 ms 는 정상 스케줄링 오차, bcrypt 1회(~0.2~0.3s) 가 0.25 구간에 잡히게
_LOOP_LAG_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)

# ── HTTP (RequestContextMiddleware 가 기록 — 액세스 로그와 같은 path 템플릿·status) ──

HTTP_REQUESTS_TOTAL = Counter(
    "rekle_http_requests_total",
    "HTTP 요청 수",
    ["method", "path", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "rekle_http_request_duration_seconds",
    "HTTP 요청 처리 시간",
    ["method", "path"],
    buckets=_HTTP_LATENCY_BUCKETS,
)
# 계속 오르면 처리 속도가 유입을 못 따라간다는 신호 — 부하테스트의 핵심 지표
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "rekle_http_requests_in_progress",
    "현재 처리 중인 HTTP 요청 수",
    multiprocess_mode="livesum",
)

# ── 런타임 (app.core.event_loop_lag 가 기록) ──────────────────────

EVENT_LOOP_LAG_SECONDS = Histogram(
    "rekle_event_loop_lag_seconds",
    "asyncio.sleep 이 예정보다 늦게 깨어난 시간 = 그동안 이벤트 루프가 막힌 시간 (워커 단위)",
    buckets=_LOOP_LAG_BUCKETS,
)

# ── DB ─────────────────────────────────────────────────────────

DB_POOL_CONNECTIONS_IN_USE = Gauge(
    "rekle_db_pool_connections_in_use",
    "풀에서 대여 중인 DB 커넥션 수 (pool_size + max_overflow 에 닿으면 요청이 대기)",
    multiprocess_mode="livesum",
)
DB_POOL_CHECKOUT_WAIT_SECONDS = Histogram(
    "rekle_db_pool_checkout_wait_seconds",
    "풀에서 DB 커넥션을 얻기까지 걸린 시간 (대기 + 필요 시 새 커넥션 생성 + pre_ping)",
    buckets=_POOL_WAIT_BUCKETS,
)
DB_POOL_TIMEOUTS_TOTAL = Counter(
    "rekle_db_pool_timeouts_total",
    "pool_timeout 안에 커넥션을 못 얻어 실패한 횟수 (API 는 503 SERVICE_BUSY)",
)

# ── 비즈니스 ───────────────────────────────────────────────────

PAYMENT_CONFIRM_TOTAL = Counter(
    "rekle_payment_confirm_total",
    "토스 결제 승인(confirm) 호출 결과",
    ["result"],  # success | failed | unknown
)
PG_REQUEST_DURATION_SECONDS = Histogram(
    "rekle_pg_request_duration_seconds",
    "토스페이먼츠 API 호출 시간 — 우리 로직과 PG 지연을 분리해서 본다",
    ["operation"],  # confirm | get_payment | get_payment_by_order_id | cancel
    buckets=_PG_LATENCY_BUCKETS,
)
PAYMENT_WEBHOOK_RECEIVED_TOTAL = Counter(
    "rekle_payment_webhook_received_total",
    "토스 웹훅 수신 (조회 API 로 재확인한 실제 결제 상태별)",
    ["remote_status"],
)
ORDERS_CREATED_TOTAL = Counter("rekle_orders_created_total", "생성된 주문 수")
SIGNUPS_TOTAL = Counter(
    "rekle_signups_total",
    "회원가입 수",
    ["provider"],  # email | kakao | naver | google
)
ABANDONED_ORDERS_RELEASED_TOTAL = Counter(
    "rekle_abandoned_orders_released_total",
    "스위퍼가 정리한 방치 PENDING 주문 수",
)


class InstrumentedAsyncAdaptedQueuePool(AsyncAdaptedQueuePool):
    """커넥션 획득 대기 시간·타임아웃을 기록하는 async 기본 풀.

    pool `checkout` 이벤트는 커넥션을 얻은 *뒤* 에 불려 대기 시간을 잴 수 없고, 획득 전 이벤트는
    없다. 그래서 엔진이 커넥션을 빌릴 때 부르는 공개 메서드 `connect()` 전체를 잰다 — 큐 대기 +
    (overflow 여유가 있으면) 새 커넥션 생성 + pre_ping. 내부 `_do_get` 은 경합 시 재귀 호출돼
    한 번의 획득이 여러 번 관측될 수 있어 쓰지 않는다.
    `engine.dispose()` 는 같은 클래스로 풀을 재생성하므로 계측이 유지된다.
    """

    def connect(self) -> PoolProxiedConnection:
        start = time.perf_counter()
        try:
            return super().connect()
        except sa_exc.TimeoutError:
            DB_POOL_TIMEOUTS_TOTAL.inc()
            raise
        finally:
            DB_POOL_CHECKOUT_WAIT_SECONDS.observe(time.perf_counter() - start)


def instrument_pool(pool: Pool) -> None:
    """커넥션 대여/반납 이벤트로 사용 중 커넥션 Gauge 를 갱신한다.

    scrape 시점에 pool 을 읽는 방식은 그 요청을 받은 워커 하나의 값만 보여서 멀티 워커에서 틀린다.
    """
    event.listen(pool, "checkout", _on_checkout)
    event.listen(pool, "checkin", _on_checkin)


def _on_checkout(*_: object) -> None:
    DB_POOL_CONNECTIONS_IN_USE.inc()


def _on_checkin(*_: object) -> None:
    DB_POOL_CONNECTIONS_IN_USE.dec()


def render_latest() -> bytes:
    """Prometheus text format. 멀티 워커면 워커별 파일을 합산한 레지스트리로 렌더한다."""
    if "PROMETHEUS_MULTIPROC_DIR" in os.environ:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        return generate_latest(registry)
    return generate_latest(REGISTRY)
