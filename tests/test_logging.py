"""app.core.logging.configure_logging — 로깅 초기화 단위 테스트.

배경: 로깅 설정이 전혀 없어서 root 로거가 WARNING·핸들러 0개 상태였고,
결제 웹훅 수신·방치 주문 정리 같은 INFO 로그가 운영에서 전부 유실됐다.
"""

import json
import logging

import pytest
import structlog

from app.core.logging import configure_logging, mask_sensitive_fields

pytestmark = pytest.mark.usefixtures("restore_logging")


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
    uvicorn_error = logging.getLogger("uvicorn.error")
    uvicorn_error.handlers = [logging.StreamHandler()]
    uvicorn_error.propagate = False
    configure_logging(level="INFO", json_logs=True)

    uvicorn_error.info("Started server process [%d]", 123)

    [line] = _json_lines(capsys.readouterr().out)
    assert line["logger"] == "uvicorn.error"
    assert line["event"] == "Started server process [123]"


def test_uvicorn_access_log_is_suppressed(capsys: pytest.CaptureFixture[str]) -> None:
    """uvicorn 기본 액세스 로그는 끈다 — 미들웨어의 구조화 액세스 로그와 이중 기록 방지."""
    configure_logging(level="INFO", json_logs=True)

    logging.getLogger("uvicorn.access").info('%s - "%s %s"', "127.0.0.1", "GET", "/")

    assert capsys.readouterr().out == ""


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


# ── 민감정보 마스킹 (O1-5) ──────────────────────────────────────


@pytest.mark.parametrize(
    "key",
    ["password", "new_password", "PASSWORD", "access_token", "refresh_token", "id_token",
     "Authorization", "client_secret", "ci", "di"],
)
def test_mask_sensitive_fields_fully_masks_secret_keys(key: str) -> None:
    """비밀번호·토큰·시크릿·CI/DI 는 키 대소문자와 무관하게 값 전체를 가린다."""
    result = mask_sensitive_fields(None, "info", {"event": "e", key: "s3cr3t-value"})

    assert result[key] == "***"


def test_mask_sensitive_fields_masks_non_string_secret() -> None:
    """문자열이 아닌 값(숫자 등)이어도 비밀 키면 가린다."""
    result = mask_sensitive_fields(None, "info", {"event": "e", "token": 123456})

    assert result["token"] == "***"


def test_mask_sensitive_fields_keeps_payment_key_prefix() -> None:
    """payment_key 는 추적용으로 앞 6자만 남긴다."""
    event = {"event": "e", "payment_key": "tgen_20261105abcdef"}

    result = mask_sensitive_fields(None, "info", event)

    assert result["payment_key"] == "tgen_2***"


def test_mask_sensitive_fields_masks_phone_middle_digits() -> None:
    """휴대폰 번호는 앞 3자리·뒤 4자리만 남기고 구분자(-)는 유지."""
    result = mask_sensitive_fields(None, "info", {"event": "e", "phone": "010-1234-5678"})

    assert result["phone"] == "010-****-5678"


def test_mask_sensitive_fields_masks_short_phone_entirely() -> None:
    """앞·뒤를 남기면 원문이 다 보이는 짧은 값은 전체를 가린다."""
    result = mask_sensitive_fields(None, "info", {"event": "e", "phone": "12345"})

    assert result["phone"] == "***"


def test_mask_sensitive_fields_masks_email_local_part() -> None:
    """이메일은 로컬파트 앞 2자 + 도메인만 남긴다."""
    result = mask_sensitive_fields(None, "info", {"event": "e", "email": "honggildong@example.com"})

    assert result["email"] == "ho***@example.com"


def test_mask_sensitive_fields_masks_malformed_email_entirely() -> None:
    """@ 가 없는 값은 형식을 알 수 없으니 전체를 가린다."""
    result = mask_sensitive_fields(None, "info", {"event": "e", "email": "not-an-email"})

    assert result["email"] == "***"


def test_mask_sensitive_fields_recurses_into_nested_dicts_and_lists() -> None:
    """중첩 dict / list 안의 민감 키도 가린다."""
    event = {"event": "e", "body": {"user": {"password": "p"}, "items": [{"token": "t"}]}}

    result = mask_sensitive_fields(None, "info", event)

    assert result["body"] == {"user": {"password": "***"}, "items": [{"token": "***"}]}


def test_mask_sensitive_fields_leaves_other_fields_untouched() -> None:
    """민감하지 않은 키(order_number, user_id 등)는 그대로 둔다."""
    event = {"event": "주문 생성", "order_number": "RK-2611050001", "user_id": 42}

    result = mask_sensitive_fields(None, "info", dict(event))

    assert result == event


def test_json_log_output_masks_sensitive_fields(capsys: pytest.CaptureFixture[str]) -> None:
    """configure_logging 체인에 마스킹이 연결돼 실제 출력에서 가려진다."""
    configure_logging(level="INFO", json_logs=True)

    structlog.stdlib.get_logger("app.test").info("로그인 실패", login_id="hong", password="pw1234")

    [line] = _json_lines(capsys.readouterr().out)
    assert line["password"] == "***"
    assert line["login_id"] == "hong"


def test_json_log_keeps_korean_event_readable(capsys: pytest.CaptureFixture[str]) -> None:
    """한국어 이벤트명이 \\uXXXX 로 이스케이프되지 않는다.

    그래야 docker logs | grep "토스 웹훅 수신" 으로 찾을 수 있다.
    """
    configure_logging(level="INFO", json_logs=True)

    structlog.stdlib.get_logger("app.test").info("토스 웹훅 수신")

    assert '"event": "토스 웹훅 수신"' in capsys.readouterr().out
