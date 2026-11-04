"""app.core.logging.configure_logging — 로깅 초기화 단위 테스트.

배경: 로깅 설정이 전혀 없어서 root 로거가 WARNING·핸들러 0개 상태였고,
결제 웹훅 수신·방치 주문 정리 같은 INFO 로그가 운영에서 전부 유실됐다.
"""

import json
import logging
from collections.abc import Iterator

import pytest
import structlog

from app.core.logging import configure_logging

_THIRD_PARTY_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """configure_logging 은 전역(root 로거·structlog) 상태를 바꾸므로 테스트마다 원복."""
    root = logging.getLogger()
    saved_root = (root.handlers[:], root.level)
    saved_third_party = {
        name: (logging.getLogger(name).handlers[:], logging.getLogger(name).propagate)
        for name in _THIRD_PARTY_LOGGERS
    }
    saved_structlog = structlog.get_config()
    yield
    root.handlers, root.level = saved_root[0], saved_root[1]
    for name, (handlers, propagate) in saved_third_party.items():
        logging.getLogger(name).handlers = handlers
        logging.getLogger(name).propagate = propagate
    structlog.configure(**saved_structlog)
    structlog.contextvars.clear_contextvars()


def _json_lines(out: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in out.strip().splitlines()]


def test_configure_logging_rejects_unknown_level() -> None:
    """존재하지 않는 레벨명은 조용히 무시하지 않고 즉시 실패한다 (설정 오타 조기 발견)."""
    with pytest.raises(ValueError):
        configure_logging(level="VERBOSE", json_logs=True)


def test_configure_logging_drops_records_below_level(capsys: pytest.CaptureFixture[str]) -> None:
    """level=WARNING 이면 INFO 는 출력되지 않는다."""
    configure_logging(level="WARNING", json_logs=True)

    logging.getLogger("app.test").info("버려질 로그")

    assert capsys.readouterr().out == ""


def test_stdlib_info_log_is_emitted_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    """기존 logging.getLogger(__name__).info(...) 호출부가 수정 없이 JSON 한 줄로 출력된다."""
    configure_logging(level="INFO", json_logs=True)

    logging.getLogger("app.payment.payment_service").info("토스 웹훅 수신")

    [line] = _json_lines(capsys.readouterr().out)
    assert line["event"] == "토스 웹훅 수신"
    assert line["level"] == "info"
    assert line["logger"] == "app.payment.payment_service"


def test_json_log_timestamp_is_utc_iso8601(capsys: pytest.CaptureFixture[str]) -> None:
    """timestamp 는 UTC ISO-8601 + Z suffix (프로젝트 UTC 규칙)."""
    configure_logging(level="INFO", json_logs=True)

    logging.getLogger("app.test").info("시각 확인")

    [line] = _json_lines(capsys.readouterr().out)
    timestamp = line["timestamp"]
    assert isinstance(timestamp, str)
    assert timestamp.endswith("Z")


def test_json_log_renders_percent_style_args(capsys: pytest.CaptureFixture[str]) -> None:
    """%-포맷 인자(logger.info("%d건", n))가 메시지에 합쳐져 출력된다."""
    configure_logging(level="INFO", json_logs=True)

    logging.getLogger("app.order.abandoned_order_sweeper").info("방치 주문 %d건 정리", 3)

    [line] = _json_lines(capsys.readouterr().out)
    assert line["event"] == "방치 주문 3건 정리"


def test_json_log_includes_exception_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    """logger.exception 의 스택트레이스가 JSON 에서 유실되지 않는다."""
    configure_logging(level="INFO", json_logs=True)

    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        logging.getLogger("app.core.exceptions").exception("Unhandled exception")

    [line] = _json_lines(capsys.readouterr().out)
    assert line["level"] == "error"
    assert "ZeroDivisionError" in str(line["exception"])


def test_json_log_includes_bound_context_vars(capsys: pytest.CaptureFixture[str]) -> None:
    """contextvars 로 바인딩한 값(request_id 등)이 모든 로그에 자동 포함된다."""
    configure_logging(level="INFO", json_logs=True)
    structlog.contextvars.bind_contextvars(request_id="req-123")

    logging.getLogger("app.test").info("컨텍스트 확인")

    [line] = _json_lines(capsys.readouterr().out)
    assert line["request_id"] == "req-123"


def test_uvicorn_logger_is_routed_through_root_once(capsys: pytest.CaptureFixture[str]) -> None:
    """uvicorn 이 자체 핸들러를 달아둔 상태여도 같은 JSON 포맷으로 한 번만 출력된다."""
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.handlers = [logging.StreamHandler()]
    uvicorn_access.propagate = False
    configure_logging(level="INFO", json_logs=True)

    uvicorn_access.info('%s - "%s %s"', "127.0.0.1", "GET", "/api/v1/products")

    [line] = _json_lines(capsys.readouterr().out)
    assert line["logger"] == "uvicorn.access"
    assert line["event"] == '127.0.0.1 - "GET /api/v1/products"'


def test_console_mode_renders_human_readable_text(capsys: pytest.CaptureFixture[str]) -> None:
    """json_logs=False(로컬)면 JSON 이 아닌 사람이 읽는 포맷."""
    configure_logging(level="INFO", json_logs=False)

    logging.getLogger("app.test").info("로컬 콘솔 로그")

    out = capsys.readouterr().out
    assert "로컬 콘솔 로그" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


def test_app_startup_enables_info_logs_for_app_loggers() -> None:
    """앱 기동(create_app) 후엔 app.* 로거의 INFO 가 활성 — 운영 유실 버그 회귀 방지.

    create_app() 을 재호출하지 않고 모듈 import 로 기동한다 — 메트릭 등 전역 등록이
    붙으면 재호출 시 중복 등록 에러가 나기 때문.
    """
    import app.main  # noqa: F401

    assert logging.getLogger("app.payment.payment_service").isEnabledFor(logging.INFO)


def test_engine_does_not_attach_its_own_log_handler() -> None:
    """engine echo=True 는 SQLAlchemy 가 자체 핸들러를 달아 root 핸들러와 SQL 이 이중 출력된다.

    DEBUG 여부와 무관하게 echo 는 끄고, SQL 로그는 로거 레벨로만 제어해야 한다.
    """
    from app.core.database import engine

    # AsyncEngine 은 echo 를 직접 노출하지 않는다 — 실제 값은 내부 동기 엔진에 있음.
    # 미지정이면 None 이라 False/None 둘 다 "꺼짐" 으로 본다.
    assert not engine.sync_engine.echo


def test_sql_logs_enabled_only_in_debug() -> None:
    """DEBUG 일 때만 sqlalchemy.engine 로거가 INFO(SQL 출력) 로 켜진다."""
    from app.core.config import settings

    sql_logger = logging.getLogger("sqlalchemy.engine")

    assert sql_logger.isEnabledFor(logging.INFO) is settings.debug
