"""RequestContextMiddleware — request_id 부여 + 구조화 액세스 로그.

테스트 전용 미니 앱에 운영과 같은 미들웨어·예외 핸들러를 붙여 ASGI 레벨로 검증한다.
"""

import json
import uuid

import httpx
import pytest
import structlog
from fastapi import FastAPI

from app.core.config import settings
from app.core.exceptions import OrderNotFoundError, register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.main import app as main_app

pytestmark = pytest.mark.usefixtures("restore_logging")

_log = structlog.stdlib.get_logger("app.test")


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/items/{item_id}")
    async def get_item(item_id: int) -> dict[str, int]:
        _log.info("아이템 조회", item_id=item_id)
        return {"id": item_id}

    @app.get("/me")
    async def me() -> dict[str, str]:
        structlog.contextvars.bind_contextvars(user_id=7)
        return {"ok": "yes"}

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("의도한 예외")

    @app.get("/missing")
    async def missing() -> None:
        raise OrderNotFoundError()

    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    # raise_app_exceptions=False — ServerErrorMiddleware 가 500 응답을 보낸 뒤 예외를 재발생시킨다
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _json_lines(out: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in out.strip().splitlines() if line.startswith("{")]


def _access_logs(out: str) -> list[dict[str, object]]:
    return [line for line in _json_lines(out) if line["event"] == "http_request"]


def _configured_app() -> FastAPI:
    # 테스트 본문에서 호출할 것 — fixture 단계에서 만든 StreamHandler 는 실행 단계의 capsys 와
    # 다른 캡처 스트림에 묶여 출력이 잡히지 않는다.
    configure_logging(level="INFO", json_logs=True)
    return _build_app()


# ── request_id ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "incoming",
    ["a" * 129, "bad id with spaces", "injected\r\nX-Evil: 1", ""],
)
async def test_request_id_replaces_invalid_incoming_header_with_new_uuid(incoming: str) -> None:
    """길이 초과·허용 외 문자·빈 값은 신뢰하지 않고 새 UUID4 를 발급한다 (로그 위조 방지)."""
    app = _configured_app()
    async with _client(app) as client:
        res = await client.get("/health", headers={REQUEST_ID_HEADER: incoming})

    request_id = res.headers[REQUEST_ID_HEADER]
    assert request_id != incoming
    assert uuid.UUID(request_id).version == 4


async def test_request_id_generates_uuid4_when_header_absent() -> None:
    """헤더가 없으면 UUID4 를 생성해 응답 헤더로 돌려준다."""
    app = _configured_app()
    async with _client(app) as client:
        res = await client.get("/health")

    assert uuid.UUID(res.headers[REQUEST_ID_HEADER]).version == 4


async def test_request_id_echoes_valid_incoming_header() -> None:
    """nginx $request_id(hex 32자) 같은 정상 값은 그대로 이어받는다 — nginx 로그와 연결."""
    app = _configured_app()
    incoming = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"
    async with _client(app) as client:
        res = await client.get("/health", headers={REQUEST_ID_HEADER: incoming})

    assert res.headers[REQUEST_ID_HEADER] == incoming


async def test_request_id_header_present_on_unhandled_500() -> None:
    """미처리 예외의 500 응답에도 request_id 가 붙는다 — 장애 문의 추적의 핵심 케이스."""
    app = _configured_app()
    async with _client(app) as client:
        res = await client.get("/boom", headers={REQUEST_ID_HEADER: "req-500"})

    assert res.status_code == 500
    assert res.headers[REQUEST_ID_HEADER] == "req-500"


async def test_request_id_header_present_on_business_error() -> None:
    """BusinessError(4xx) 응답에도 request_id 가 붙는다."""
    app = _configured_app()
    async with _client(app) as client:
        res = await client.get("/missing", headers={REQUEST_ID_HEADER: "req-404"})

    assert res.status_code == 404
    assert res.headers[REQUEST_ID_HEADER] == "req-404"


async def test_request_id_is_bound_to_logs_inside_request(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """핸들러 안에서 찍은 로그에 request_id 가 자동으로 포함된다."""
    app = _configured_app()
    async with _client(app) as client:
        await client.get("/items/3", headers={REQUEST_ID_HEADER: "req-abc"})

    [line] = [ln for ln in _json_lines(capsys.readouterr().out) if ln["event"] == "아이템 조회"]
    assert line["request_id"] == "req-abc"


async def test_unhandled_exception_log_includes_request_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """500 핸들러의 에러 로그에도 request_id 가 남는다 (응답 헤더 값으로 로그 검색 가능)."""
    app = _configured_app()
    async with _client(app) as client:
        await client.get("/boom", headers={REQUEST_ID_HEADER: "req-err"})

    errors = [ln for ln in _json_lines(capsys.readouterr().out) if ln["level"] == "error"]
    assert errors
    assert errors[0]["request_id"] == "req-err"


async def test_context_from_previous_request_does_not_leak(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """앞 요청에서 바인딩한 user_id 가 다음 요청 로그로 새지 않는다."""
    app = _configured_app()
    async with _client(app) as client:
        await client.get("/me")
        await client.get("/items/1")

    [line] = [ln for ln in _json_lines(capsys.readouterr().out) if ln["event"] == "아이템 조회"]
    assert "user_id" not in line


# ── 액세스 로그 ───────────────────────────────────────────────


async def test_access_log_uses_route_template_not_raw_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """path 는 실제 값(/items/3)이 아니라 라우트 템플릿 — 검색·집계 시 종류 폭발 방지."""
    app = _configured_app()
    async with _client(app) as client:
        await client.get("/items/3", headers={REQUEST_ID_HEADER: "req-1"})

    [line] = _access_logs(capsys.readouterr().out)
    assert line["path"] == "/items/{item_id}"
    assert line["method"] == "GET"
    assert line["status"] == 200
    assert line["request_id"] == "req-1"
    assert line["client_ip"] == "127.0.0.1"
    assert isinstance(line["duration_ms"], float)


async def test_access_log_marks_unmatched_path_without_raw_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """매칭되는 라우트가 없으면(스캐너의 무작위 경로 등) 원문 대신 고정값으로 기록."""
    app = _configured_app()
    async with _client(app) as client:
        res = await client.get("/wp-admin/../../etc/passwd")

    [line] = _access_logs(capsys.readouterr().out)
    assert res.status_code == 404
    assert line["path"] == "<unmatched>"


async def test_access_log_records_500_for_unhandled_exception(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """미처리 예외는 응답 시작 전에 미들웨어를 빠져나가도 status 500 으로 기록."""
    app = _configured_app()
    async with _client(app) as client:
        await client.get("/boom")

    [line] = _access_logs(capsys.readouterr().out)
    assert line["status"] == 500
    assert line["path"] == "/boom"


async def test_access_log_includes_user_id_bound_during_request(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """인증 dependency 가 요청 중 바인딩한 user_id 가 액세스 로그에 포함된다."""
    app = _configured_app()
    async with _client(app) as client:
        await client.get("/me")

    [line] = _access_logs(capsys.readouterr().out)
    assert line["user_id"] == 7


async def test_access_log_skips_health_but_still_sets_request_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """헬스체크는 1분마다 들어오는 노이즈라 액세스 로그에서 제외 — 헤더는 그대로."""
    app = _configured_app()
    async with _client(app) as client:
        res = await client.get("/health")

    assert _access_logs(capsys.readouterr().out) == []
    assert REQUEST_ID_HEADER in res.headers


async def test_business_error_is_logged_at_info_with_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """BusinessError 는 정상 거절이라 INFO — 에러 코드가 남아 액세스 로그만으론 모르는 사유 확인."""
    app = _configured_app()
    async with _client(app) as client:
        await client.get("/missing")

    [line] = [ln for ln in _json_lines(capsys.readouterr().out) if ln["event"] == "비즈니스 예외"]
    assert line["level"] == "info"
    assert line["code"] == "ORDER_NOT_FOUND"
    assert line["status"] == 404


async def test_non_http_scope_passes_through() -> None:
    """lifespan 같은 non-http scope 는 건드리지 않고 그대로 통과시킨다."""
    received: list[str] = []

    async def inner(scope: dict[str, object], receive: object, send: object) -> None:
        received.append(str(scope["type"]))

    middleware = RequestContextMiddleware(inner)  # type: ignore[arg-type]
    await middleware({"type": "lifespan"}, None, None)  # type: ignore[arg-type]

    assert received == ["lifespan"]


async def test_main_app_cors_exposes_request_id_header() -> None:
    """운영 앱 CORS 가 X-Request-ID 를 expose — 안 하면 브라우저 JS 가 헤더를 읽지 못한다."""
    if not settings.cors_origins:
        pytest.skip("CORS_ORIGINS 미설정 환경")
    origin = settings.cors_origins[0]

    async with _client(main_app) as client:
        res = await client.get("/health", headers={"Origin": origin})

    exposed = res.headers.get("access-control-expose-headers", "")
    assert REQUEST_ID_HEADER.lower() in exposed.lower()
    assert REQUEST_ID_HEADER in res.headers
