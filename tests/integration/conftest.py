"""실제 DB 대상 통합 테스트 공용 fixture.

asyncpg 커넥션은 생성 시점의 이벤트 루프에 종속된다. pytest-asyncio 는
테스트마다 새 이벤트 루프를 만들기 때문에, `app.core.database.engine` 의
커넥션 풀에 이전 루프에서 만든 커넥션이 남아있으면 다음 테스트에서
"Event loop is closed" 로 깨진다. `db_session` 을 요청한 테스트가 끝날
때마다 풀을 비워 다음 테스트가 현재 루프에서 커넥션을 새로 맺도록 강제한다.

DB 를 쓰지 않는 테스트(dependency_overrides 로 fake 서비스를 주입하는
라우터 테스트 등)는 이 fixture를 요청하지 않으므로 영향받지 않는다 —
autouse 로 전체 `tests/integration/` 에 걸면 DB 를 안 쓰는 테스트까지
매번 이벤트 루프/dispose 비용을 물게 된다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
    await engine.dispose()
