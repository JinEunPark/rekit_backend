"""전화번호 하이픈 포맷 백필 (users, addresses, orders)

Revision ID: ea245030888c
Revises: 6105137b8e93
Create Date: 2026-08-18 14:31:41.641387+09:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'ea245030888c'
down_revision: Union[str, None] = '6105137b8e93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# app/core/phone.py::normalize_phone 와 동일한 규칙(01[016789] + 7~8자리)을
# SQL 정규식으로 이식. 하이픈 없는 순수 숫자만 매칭되므로 이미 정규화된 값과
# NULL/빈 문자열은 WHERE 절에서 자동 제외된다.
_TABLES_AND_COLUMNS = (
    ("users", "phone"),
    ("addresses", "phone"),
    ("orders", "recipient_phone"),
)


def upgrade() -> None:
    for table, column in _TABLES_AND_COLUMNS:
        # 11자리 (010-0000-0000): 3-4-4
        op.execute(
            f"""
            UPDATE {table}
            SET {column} = regexp_replace({column}, '^(01[016789])(\\d{{4}})(\\d{{4}})$', '\\1-\\2-\\3')
            WHERE {column} ~ '^01[016789]\\d{{8}}$'
            """
        )
        # 구형 10자리 (011-000-0000): 3-3-4
        op.execute(
            f"""
            UPDATE {table}
            SET {column} = regexp_replace({column}, '^(01[016789])(\\d{{3}})(\\d{{4}})$', '\\1-\\2-\\3')
            WHERE {column} ~ '^01[016789]\\d{{7}}$'
            """
        )


def downgrade() -> None:
    for table, column in _TABLES_AND_COLUMNS:
        op.execute(
            f"""
            UPDATE {table}
            SET {column} = replace({column}, '-', '')
            WHERE {column} ~ '^01[016789][0-9]*-'
            """
        )
