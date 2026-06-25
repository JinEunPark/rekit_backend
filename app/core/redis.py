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

from redis.asyncio import Redis

from app.core.config import settings


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    """FastAPI Depends() 진입점. 프로세스 단위 싱글턴 (lru_cache 1슬롯)."""
    return Redis.from_url(settings.redis_url, decode_responses=True)
