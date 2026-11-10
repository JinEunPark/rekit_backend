"""Redis 비동기 클라이언트 — 앱 전역 싱글턴.

`get_redis()` 를 FastAPI Depends() 로 주입받아 사용한다.
decode_responses=True 로 설정해 bytes 대신 str 이 반환된다.

사용처:
- 이메일 인증 코드 임시 저장 (TTL 10분)
- SMS 인증 코드 임시 저장 (TTL 5분) — 추후 구현
- rate-limit 센티넬 (TTL 60초)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from redis.asyncio import Redis

from app.core.config import settings
from app.core.metrics import observe_external_call


class InstrumentedRedis(Redis):
    """명령마다 소요 시간을 외부 호출 metric(service=redis)에 기록하는 클라이언트.

    get/set/delete 등 모든 단일 명령이 `execute_command` 하나를 거쳐서 여기만 감싸면 된다
    (pipeline 은 별도 경로 — 현재 앱에서 안 씀). operation 은 명령 이름이라 종류가 손에 꼽힌다.
    """

    async def execute_command(self, *args: Any, **options: Any) -> Any:
        with observe_external_call("redis", str(args[0]).lower()):
            # redis-py 가 execute_command 에 타입을 안 달아 둠
            return await super().execute_command(*args, **options)  # type: ignore[no-untyped-call]


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    """FastAPI Depends() 진입점. 프로세스 단위 싱글턴 (lru_cache 1슬롯)."""
    return InstrumentedRedis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=settings.redis_socket_timeout,
        socket_connect_timeout=settings.redis_socket_connect_timeout,
        max_connections=settings.redis_max_connections,
    )
