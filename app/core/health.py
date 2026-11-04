"""readiness 체크 — DB·Redis 가 실제로 응답하는지 (Spring Actuator health 의 readiness 대응).

/health(liveness)는 의존성을 보지 않는다. 의존성 장애에 liveness 가 실패하면 컨테이너가
재시작을 반복해 복구를 더 늦춘다.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping

import structlog
from sqlalchemy import text

from app.core.database import engine
from app.core.redis import get_redis

ReadinessCheck = Callable[[], Awaitable[object]]

# 외부 업타임 모니터(1분 주기)가 기다리는 시간 안에 끝나야 한다
READINESS_TIMEOUT_SECONDS = 2.0

_log = structlog.stdlib.get_logger(__name__)


async def check_database() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def check_redis() -> None:
    # redis-py 타입 스텁이 sync/async 겸용이라 Awaitable[bool] | bool —
    # asyncio 클라이언트는 항상 awaitable
    await get_redis().ping()  # type: ignore[misc]


def get_readiness_checks() -> Mapping[str, ReadinessCheck]:
    """FastAPI Depends 진입점 — 테스트는 dependency_overrides 로 장애를 주입한다."""
    return {"database": check_database, "redis": check_redis}


async def _run_one(name: str, check: ReadinessCheck, timeout: float) -> str:
    try:
        await asyncio.wait_for(check(), timeout)
    except TimeoutError:
        _log.warning("readiness 체크 타임아웃", dependency=name, timeout_seconds=timeout)
        return "timeout"
    except Exception as exc:
        _log.warning("readiness 체크 실패", dependency=name, error=repr(exc))
        return "fail"
    return "ok"


async def run_checks(checks: Mapping[str, ReadinessCheck], *, timeout: float) -> dict[str, str]:
    """의존성별 결과 — 하나가 실패해도 나머지를 계속 확인해 어느 쪽이 문제인지 알려준다."""
    results = await asyncio.gather(*(_run_one(name, c, timeout) for name, c in checks.items()))
    return dict(zip(checks, results, strict=True))
