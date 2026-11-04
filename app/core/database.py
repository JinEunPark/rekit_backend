import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,
)

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
