"""DB 타임아웃·보호 설정 (todo O4b-1·O4b-2).

부하 시 "무한 대기" 를 막는 값들이 실제 엔진/응답에 반영되는지 검증한다.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import exc as sa_exc
from sqlalchemy.pool import QueuePool

from app.core.config import settings
from app.core.database import engine
from app.core.exceptions import register_exception_handlers
from app.main import install_middlewares


def test_engine_pool_timeout_uses_setting() -> None:
    """풀 고갈 시 기본 30초 대신 설정값만큼만 기다린다 — 요청이 30초씩 쌓이는 것 방지."""
    pool = engine.sync_engine.pool
    assert isinstance(pool, QueuePool)
    assert pool.timeout() == settings.database_pool_timeout


def test_pool_timeout_error_returns_503_standard_error() -> None:
    """풀 대기 타임아웃은 500(버그) 이 아니라 503(일시 과부하) + 표준 에러 포맷으로 응답한다."""
    app = FastAPI()
    install_middlewares(app, cors_origins=[])
    register_exception_handlers(app)

    @app.get("/busy")
    async def _busy() -> None:
        raise sa_exc.TimeoutError("QueuePool limit of size 5 overflow 10 reached")

    res = TestClient(app).get("/busy")

    assert res.status_code == 503
    assert res.json()["error"]["code"] == "SERVICE_BUSY"
    assert "QueuePool" not in res.text


async def _pg_setting_ms(name: str) -> int:
    from sqlalchemy import text

    # 앞선 테스트 루프의 커넥션이 풀에 남아 있으면 "attached to a different loop" — 비우고 시작
    await engine.dispose()
    try:
        async with engine.connect() as conn:
            value = await conn.scalar(
                text("SELECT setting FROM pg_settings WHERE name = :name"), {"name": name}
            )
    finally:
        await engine.dispose()
    return int(value)


async def test_engine_connection_applies_statement_timeout() -> None:
    """느린 쿼리·락 대기가 커넥션을 무기한 점유하지 않게 세션 statement_timeout 을 건다."""
    assert await _pg_setting_ms("statement_timeout") == settings.database_statement_timeout_ms


async def test_engine_connection_applies_idle_in_transaction_timeout() -> None:
    """트랜잭션을 연 채 방치된 세션(락 보유)은 서버가 끊는다."""
    assert (
        await _pg_setting_ms("idle_in_transaction_session_timeout")
        == settings.database_idle_in_transaction_timeout_ms
    )
