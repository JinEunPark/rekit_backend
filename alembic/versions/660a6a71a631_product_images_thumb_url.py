"""product_images thumb_url

카드(약 200px)에 상세용 1600px 이미지를 내려보내지 않도록 긴 변 480px 썸네일 URL 컬럼 추가.
NULL 허용 — 기존 행은 catalog_utils.thumbnail_url 이 url 로 폴백하므로 백필 전에도 안전하다.
(autogenerate 가 함께 잡은 addresses/users 주석·server_default 차이는 이번 변경과 무관해 제외)

Revision ID: 660a6a71a631
Revises: a7c3e9f1b2d4
Create Date: 2026-11-13 02:22:04.921262+09:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '660a6a71a631'
down_revision: Union[str, None] = 'a7c3e9f1b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'product_images',
        sa.Column(
            'thumb_url',
            sa.String(length=500),
            nullable=True,
            comment='카드용 썸네일(긴 변 480px) URL. NULL 이면 url 로 폴백',
        ),
    )


def downgrade() -> None:
    op.drop_column('product_images', 'thumb_url')
