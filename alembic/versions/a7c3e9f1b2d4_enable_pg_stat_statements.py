"""enable pg_stat_statements

쿼리별 호출 수·평균 시간 수집 (N+1·느린 쿼리 식별, 부하테스트 분석용).
확장 객체(뷰·함수)만 만든다 — 실제 수집은 서버가 shared_preload_libraries 로 라이브러리를
올려야 동작하고, 그건 docker-compose 의 postgres command 가 담당한다.
preload 없이도 CREATE EXTENSION 자체는 성공하므로 이 마이그레이션은 어느 환경에서도 안전하다.

Revision ID: a7c3e9f1b2d4
Revises: 0181744e708f
Create Date: 2026-11-10 00:00:00+00:00

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a7c3e9f1b2d4'
down_revision: Union[str, None] = '0181744e708f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_stat_statements")
