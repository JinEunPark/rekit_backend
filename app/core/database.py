import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.metrics import InstrumentedAsyncAdaptedQueuePool, instrument_pool

engine = create_async_engine(
    settings.database_url,
    poolclass=InstrumentedAsyncAdaptedQueuePool,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout,
    pool_pre_ping=True,
    # asyncpg 가 접속 시 SET 해 두는 세션 설정. alembic/env.py 는 별도 엔진이라 마이그레이션(긴 DDL·
    # 인덱스 생성)엔 걸리지 않는다
    connect_args={
        "server_settings": {
            "statement_timeout": str(settings.database_statement_timeout_ms),
            "idle_in_transaction_session_timeout": str(
                settings.database_idle_in_transaction_timeout_ms
            ),
        }
    },
)

instrument_pool(engine.sync_engine.pool)

# echo=True 대신 레벨만 올린다 — echo 는 SQLAlchemy 가 자체 핸들러를 달아서 root 핸들러
# (app.core.logging) 와 SQL 이 이중 출력된다. 레벨만 올리면 root 포맷으로 한 번 출력.
if settings.debug:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)
