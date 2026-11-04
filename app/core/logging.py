"""로깅 초기화 — structlog + 표준 logging 통합.

기존 `logging.getLogger(__name__)` 호출부는 그대로 두고 출력 포맷만 structlog 로 통일한다.
운영(json_logs=True)은 JSON 한 줄(수집·검색용), 로컬은 사람이 읽는 컬러 콘솔.

설정을 안 하면 root 로거가 WARNING·핸들러 0개라 INFO 가 전부 버려진다 —
create_app() 초입에서 반드시 호출할 것.
"""

import logging
import sys

import structlog
from structlog.typing import Processor

# uvicorn 은 자기 로거에 전용 핸들러를 달고 propagate=False 로 둔다 (gunicorn 워커도 동일).
# 그대로 두면 포맷이 제각각이라 핸들러를 걷어내고 root 로 올려 한 포맷으로 통일한다.
_THIRD_PARTY_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def configure_logging(*, level: str, json_logs: bool) -> None:
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderers: list[Processor]
    if json_logs:
        # ProcessorFormatter 는 exc_info 를 event dict 에 넘기기만 한다 — 문자열화하지 않으면
        # JSON 에서 스택트레이스가 사라진다. (ConsoleRenderer 는 자체적으로 예쁘게 출력)
        renderers = [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
    else:
        renderers = [structlog.dev.ConsoleRenderer()]

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *renderers],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers = [handler]

    for name in _THIRD_PARTY_LOGGERS:
        third_party = logging.getLogger(name)
        third_party.handlers.clear()
        third_party.propagate = True
