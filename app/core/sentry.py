"""Sentry 에러 추적 초기화.

DSN 이 없으면(로컬·테스트 기본) 아무것도 하지 않는다. 켜지면 미처리 예외와 ERROR 레벨 로그
(결제 이상 감지 등 — LoggingIntegration 기본값)가 이슈로 모이고 알림을 받을 수 있다.
"""

from typing import Any

import sentry_sdk
import structlog
from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

from app.core.exceptions import BusinessError

# Sentry 기본 목록(password·token·secret·authorization…)에 없는 프로젝트 민감 키
# — 로그 마스킹(app.core.logging)과 같은 기준
_EXTRA_DENYLIST = ["payment_key", "phone", "email", "ci", "di"]


def before_send(event: Any, hint: Any) -> Any:
    exc_info = hint.get("exc_info")
    # 정상적인 4xx 거절이 이슈로 쌓이면 진짜 장애가 묻힌다
    if exc_info and isinstance(exc_info[1], BusinessError):
        return None

    context = structlog.contextvars.get_contextvars()
    if request_id := context.get("request_id"):
        event.setdefault("tags", {})["request_id"] = request_id
    if (user_id := context.get("user_id")) is not None:
        event["user"] = {"id": str(user_id)}
    return event


def init_sentry(
    *, dsn: str | None, environment: str, release: str, traces_sample_rate: float
) -> bool:
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
        event_scrubber=EventScrubber(
            denylist=[*DEFAULT_DENYLIST, *_EXTRA_DENYLIST], recursive=True
        ),
        before_send=before_send,
    )
    return True
