"""app.core.redis 클라이언트 보호 설정 (todo O4b-3).

타임아웃이 없으면 Redis 가 멈췄을 때 요청도 무기한 멈춘다.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.redis import get_redis


def test_redis_client_applies_socket_timeouts_from_settings() -> None:
    """명령 응답·접속 모두 설정값에서 끊는다 — Redis 행이 요청 행으로 번지지 않게."""
    kwargs = get_redis().connection_pool.connection_kwargs

    assert kwargs["socket_timeout"] == settings.redis_socket_timeout
    assert kwargs["socket_connect_timeout"] == settings.redis_socket_connect_timeout


def test_redis_client_caps_pool_connections_from_settings() -> None:
    """워커당 커넥션 수 상한 — 부하 시 Redis maxclients 를 소진하지 않게."""
    assert get_redis().connection_pool.max_connections == settings.redis_max_connections
