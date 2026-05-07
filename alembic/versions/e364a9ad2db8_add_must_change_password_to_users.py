"""add must_change_password to users

Revision ID: e364a9ad2db8
Revises: c1a4d8e2f6b3
Create Date: 2026-05-07 10:43:13.706830+09:00

임시 비밀번호 발급 / 강제 변경 흐름을 위한 컬럼.
- find-password 로 임시 비번 발급 시 True
- 사용자가 새 비번 설정 시 False
- True 동안엔 인증 가드가 비번 변경 외 endpoint 차단
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e364a9ad2db8"
down_revision: str | None = "c1a4d8e2f6b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment=(
                "임시 비밀번호로 발급된 상태인지 여부. "
                "find-password 로 임시 비번 발급 시 True, 사용자가 새 비번 설정 시 False. "
                "True 동안엔 비번 변경 외 다른 endpoint 가 인증 가드에서 차단된다."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
