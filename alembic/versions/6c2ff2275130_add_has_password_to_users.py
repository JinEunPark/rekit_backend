"""add has_password to users

Revision ID: 6c2ff2275130
Revises: ea245030888c
Create Date: 2026-08-26 21:34:34.097814+09:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6c2ff2275130'
down_revision: Union[str, None] = 'ea245030888c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'has_password',
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
            comment='사용자가 아는 실제 비밀번호 보유 여부. 소셜 전용 가입 시 False'
            ' (password_hash 는 추측 불가한 더미값) — DELETE /users/me 본인확인 방식 분기 기준',
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'has_password')
