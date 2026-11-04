"""HTTP 공통 미들웨어.

RequestContextMiddleware — 요청마다 request_id 를 부여하고(로그 상관 ID, Spring MDC 대응)
요청 1건당 구조화 액세스 로그 1줄을 남긴다.
UnhandledExceptionMiddleware — 미처리 예외를 CORS 안쪽에서 표준 500 응답으로 바꾼다.

순수 ASGI 로 구현한다. BaseHTTPMiddleware 는 하위 앱을 별도 task 로 돌려서, 인증
dependency 가 바인딩한 user_id 같은 contextvars 가 미들웨어로 돌아오지 않는다.
"""

import re
import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.routing import replace_params
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.exceptions import internal_error_response
from app.core.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_IN_PROGRESS,
    HTTP_REQUESTS_TOTAL,
)

REQUEST_ID_HEADER = "X-Request-ID"

# 외부에서 들어온 값은 로그에 그대로 박히므로 형식을 제한한다 (개행·공백으로 로그 위조 방지).
# nginx $request_id(hex 32자)와 UUID 를 모두 수용.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

# 1분 주기 헬스체크·Prometheus 수집이 액세스 로그·HTTP 메트릭(RPS)을 덮지 않게 제외
_ACCESS_LOG_EXCLUDED_PATHS = frozenset({"/health", "/health/ready", "/metrics"})

# 라우트 매칭 실패 시 원문 경로 대신 기록 — 스캐너의 무작위 경로로 값 종류가 폭발하지 않게
_UNMATCHED_PATH = "<unmatched>"

_access_log = structlog.stdlib.get_logger("app.access")


def _resolve_request_id(headers: Headers) -> str:
    incoming = headers.get(REQUEST_ID_HEADER)
    if incoming and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return str(uuid.uuid4())


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    template = getattr(route, "path", None)
    if route is None or not isinstance(template, str):
        return _UNMATCHED_PATH
    # FastAPI 0.162+ 는 include_router 가 라우트를 평탄화하지 않아 route.path 에 바깥 라우터
    # prefix(/api/v1)가 빠진다 (0.136 은 포함). 템플릿에 실제 파라미터를 채운 "꼬리" 가 원본 경로의
    # 끝과 같으면 그 앞부분이 생략된 prefix — 비공개 내부 구조 없이 버전과 무관하게 복원한다.
    # replace_params 는 넘긴 dict 를 pop 하므로 복사본을 넘긴다.
    rendered, _ = replace_params(
        route.path_format, route.param_convertors, dict(scope.get("path_params", {}))
    )
    raw_path: str = scope["path"]
    if rendered and raw_path.endswith(rendered):
        return raw_path[: len(raw_path) - len(rendered)] + template
    return template


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _resolve_request_id(Headers(scope=scope))
        # 요청 시작 시에만 비운다 — 끝에서 비우면 바깥 ServerErrorMiddleware 의 500 핸들러가
        # request_id 를 잃는다. 요청마다 task(=컨텍스트)가 분리돼 있어 다음 요청으로 새지 않음.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status_code = 500  # 응답 시작 전에 예외로 빠져나가면 ServerErrorMiddleware 가 500 응답
        observed = scope["path"] not in _ACCESS_LOG_EXCLUDED_PATHS
        if observed:
            HTTP_REQUESTS_IN_PROGRESS.inc()
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            if observed:
                elapsed = time.perf_counter() - started
                method, path = scope["method"], _route_template(scope)
                HTTP_REQUESTS_IN_PROGRESS.dec()
                HTTP_REQUESTS_TOTAL.labels(method=method, path=path, status=str(status_code)).inc()
                HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path=path).observe(elapsed)
                client = scope.get("client")
                _access_log.info(
                    "http_request",
                    method=method,
                    path=path,
                    status=status_code,
                    duration_ms=round(elapsed * 1000, 2),
                    client_ip=client[0] if client else None,
                )


class UnhandledExceptionMiddleware:
    """라우트의 미처리 예외를 CORS 안쪽에서 표준 500 응답으로 바꾼다.

    Starlette 는 `Exception` 핸들러를 모든 사용자 미들웨어 바깥(ServerErrorMiddleware)에 붙여서
    그 500 응답엔 Access-Control-Allow-Origin 이 없다 → 브라우저는 서버 오류를 CORS 에러로 오인.
    가장 안쪽 사용자 미들웨어로 두면 응답이 CORS·RequestContextMiddleware 를 거쳐 나간다.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_tracking_start(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_tracking_start)
        except Exception as exc:
            # 헤더를 이미 보낸 스트리밍 도중 예외는 500 으로 바꿀 수 없다 — 바깥 fallback 에 맡긴다
            if response_started:
                raise
            # 재발생시키지 않는다 — 여기서 로그를 남겼으니 ServerErrorMiddleware·uvicorn 이
            # 같은 traceback 을 한 번 더 찍지 않게
            await internal_error_response(exc)(scope, receive, send)
