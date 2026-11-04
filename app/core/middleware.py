"""HTTP 공통 미들웨어.

RequestContextMiddleware — 요청마다 request_id 를 부여하고(로그 상관 ID, Spring MDC 대응)
요청 1건당 구조화 액세스 로그 1줄을 남긴다.

순수 ASGI 로 구현한다. BaseHTTPMiddleware 는 하위 앱을 별도 task 로 돌려서, 인증
dependency 가 바인딩한 user_id 같은 contextvars 가 미들웨어로 돌아오지 않는다.
"""

import re
import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"

# 외부에서 들어온 값은 로그에 그대로 박히므로 형식을 제한한다 (개행·공백으로 로그 위조 방지).
# nginx $request_id(hex 32자)와 UUID 를 모두 수용.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

# 1분 주기 헬스체크·Prometheus 수집이 액세스 로그를 덮지 않게 제외
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
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else _UNMATCHED_PATH


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
            if scope["path"] not in _ACCESS_LOG_EXCLUDED_PATHS:
                client = scope.get("client")
                _access_log.info(
                    "http_request",
                    method=scope["method"],
                    path=_route_template(scope),
                    status=status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                    client_ip=client[0] if client else None,
                )
