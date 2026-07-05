"""admin dashboard 서비스 통합 테스트 — 실제 Postgres 대상.

get_sales_chart 의 date_trunc GROUP BY 버그는 SQL 구조 자체의 문제라
fake repo 기반 단위 테스트로는 재현되지 않는다 (Postgres 플래너가 SELECT/GROUP BY/
ORDER BY 표현식의 동일성을 파싱 시점에 검증하므로, 매칭되는 행이 없어도 재현됨).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.dashboard_service import DashboardService


@pytest.mark.asyncio
async def test_get_sales_chart_does_not_raise_grouping_error(db_session: AsyncSession):
    """date_trunc 표현식이 SELECT/GROUP BY/ORDER BY에서 동일 표현식으로 바인딩돼야 한다."""
    service = DashboardService(db_session)

    result = await service.get_sales_chart("7d")

    assert result.period == "7d"
