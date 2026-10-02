"""add image_url to product_categories

Revision ID: 0181744e708f
Revises: 6c2ff2275130
Create Date: 2026-10-02 21:04:05.504628+09:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0181744e708f'
down_revision: Union[str, None] = '6c2ff2275130'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'product_categories',
        sa.Column(
            'image_url',
            sa.String(length=500),
            nullable=True,
            comment='카테고리 대표 이미지 S3 URL (uploads/confirm 통과). NULL 이면 아이콘만 노출',
        ),
    )


def downgrade() -> None:
    op.drop_column('product_categories', 'image_url')
