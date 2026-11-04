"""로깅 초기화 — structlog + 표준 logging 통합.

`logging.getLogger(__name__)` 로 찍든 `structlog.stdlib.get_logger(__name__)` 로 찍든
같은 root 핸들러를 거쳐 한 포맷으로 출력된다.
운영(json_logs=True)은 JSON 한 줄(수집·검색용), 로컬은 사람이 읽는 컬러 콘솔.

설정을 안 하면 root 로거가 WARNING·핸들러 0개라 INFO 가 전부 버려진다 —
create_app() 초입에서 반드시 호출할 것.
"""

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

# uvicorn 은 자기 로거에 전용 핸들러를 달고 propagate=False 로 둔다 (gunicorn 워커도 동일).
# 그대로 두면 포맷이 제각각이라 핸들러를 걷어내고 root 로 올려 한 포맷으로 통일한다.
_THIRD_PARTY_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

# ── 민감정보 마스킹 ──────────────────────────────────────────────
# 키 이름(소문자) 기준. 부분 일치라 new_password·client_secret·id_token 도 잡힌다.
_FULL_MASK_SUBSTRINGS = ("password", "token", "secret", "authorization")
_FULL_MASK_EXACT = frozenset({"ci", "di"})
_MASK = "***"
_PAYMENT_KEY_VISIBLE = 6  # 토스 대시보드에서 거래를 찾을 수 있을 만큼만 남긴다
_PHONE_HEAD, _PHONE_TAIL = 3, 4
_EMAIL_LOCAL_VISIBLE = 2
_DIGIT = re.compile(r"\d")


def _mask_phone(value: str) -> str:
    if len(value) <= _PHONE_HEAD + _PHONE_TAIL:
        return _MASK
    middle = _DIGIT.sub("*", value[_PHONE_HEAD:-_PHONE_TAIL])
    return value[:_PHONE_HEAD] + middle + value[-_PHONE_TAIL:]


def _mask_email(value: str) -> str:
    local, sep, domain = value.partition("@")
    if not sep or not local:
        return _MASK
    return f"{local[:_EMAIL_LOCAL_VISIBLE]}***@{domain}"


def _mask_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if lowered in _FULL_MASK_EXACT or any(s in lowered for s in _FULL_MASK_SUBSTRINGS):
        return _MASK
    if lowered == "payment_key":
        return f"{value[:_PAYMENT_KEY_VISIBLE]}***" if isinstance(value, str) else _MASK
    if "phone" in lowered:
        return _mask_phone(value) if isinstance(value, str) else _MASK
    if "email" in lowered:
        return _mask_email(value) if isinstance(value, str) else _MASK
    return _mask_nested(value)


def _mask_nested(value: Any) -> Any:
    if isinstance(value, MutableMapping):
        return {k: _mask_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_mask_nested(v) for v in value]
    return value


def mask_sensitive_fields(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """structlog processor — 비밀번호·토큰·연락처 등 키 이름으로 민감값을 가린다.

    event(메시지 본문) 문자열 안에 섞인 값은 못 가린다 — 민감값은 반드시 키워드 인자로 넘길 것.
    """
    return {k: v if k == "event" else _mask_value(k, v) for k, v in event_dict.items()}


_SHARED_PROCESSORS: list[Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
]


def build_formatter(*, json_logs: bool) -> structlog.stdlib.ProcessorFormatter:
    """앱(configure_logging)과 gunicorn master(gunicorn_logconfig_dict)가 같이 쓰는 formatter."""
    renderers: list[Processor]
    if json_logs:
        # ProcessorFormatter 는 exc_info 를 event dict 에 넘기기만 한다 — 문자열화하지 않으면
        # JSON 에서 스택트레이스가 사라진다. (ConsoleRenderer 는 자체적으로 예쁘게 출력)
        # ensure_ascii=False — 한국어 이벤트명이 \uXXXX 로 깨지면 docker logs 에서 grep 이 안 된다
        renderers = [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ]
    else:
        renderers = [structlog.dev.ConsoleRenderer()]

    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_SHARED_PROCESSORS,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            mask_sensitive_fields,
            *renderers,
        ],
    )


def configure_logging(*, level: str, json_logs: bool) -> None:
    structlog.configure(
        processors=[*_SHARED_PROCESSORS, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # 캐시하면 로거가 첫 사용 시점 설정에 고정된다 — 이후 configure 재호출이나
        # structlog.testing.capture_logs 가 반영되지 않음. 이 트래픽 규모에선 비용 무시 가능.
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(build_formatter(json_logs=json_logs))

    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers = [handler]

    for name in _THIRD_PARTY_LOGGERS:
        third_party = logging.getLogger(name)
        third_party.handlers.clear()
        third_party.propagate = True
    # RequestContextMiddleware 가 템플릿 경로·request_id 를 담은 액세스 로그를 남긴다
    # — uvicorn 기본 액세스 로그는 꺼서 이중 기록 방지
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def gunicorn_logconfig_dict(*, level: str, json_logs: bool) -> dict[str, Any]:
    """gunicorn.conf.py 의 logconfig_dict — master 로그(Booting worker 등)를 앱과 같은 포맷으로.

    master 는 앱을 import 하기 전에 로그를 찍어 configure_logging 영향 밖이다. gunicorn 은 이
    dict 로 기본 설정(CONFIG_DEFAULTS)의 키를 통째로 덮어쓰므로 root/loggers/handlers/formatters
    를 모두 준다.
    gunicorn.* 는 자기 핸들러 없이 root 로 전파 — 워커에선 configure_logging 이 root 핸들러를
    같은 포맷으로 교체하므로 어느 프로세스에서든 한 번만 출력된다.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"structlog": {"()": build_formatter, "json_logs": json_logs}},
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "formatter": "structlog",
                "stream": "ext://sys.stdout",
            }
        },
        "root": {"level": level.upper(), "handlers": ["stdout"]},
        "loggers": {
            name: {"level": level.upper(), "handlers": [], "propagate": True}
            for name in ("gunicorn.error", "gunicorn.access")
        },
    }
