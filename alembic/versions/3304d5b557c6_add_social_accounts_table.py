"""add social_accounts table

Revision ID: 3304d5b557c6
Revises: e364a9ad2db8
Create Date: 2026-05-10 13:07:22.152124+09:00

소셜 로그인 연결 (User 1:N SocialAccount). provider+social_id 유니크 — 동일 카카오
계정으로 다른 rekit User 에 중복 연결 차단. user_id 인덱스로 마이페이지에서
"연결된 소셜 목록" 조회를 빠르게.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3304d5b557c6"
down_revision: str | None = "e364a9ad2db8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "social_accounts",
        sa.Column(
            "id",
            sa.Integer(),
            sa.Identity(always=False),
            nullable=False,
            comment="소셜 연결 PK",
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
            comment="연결된 rekit User FK. 회원 탈퇴 시 cascade 정리",
        ),
        sa.Column(
            "provider",
            sa.Enum("KAKAO", "NAVER", name="socialprovider", native_enum=False, length=20),
            nullable=False,
            comment="소셜 PG (kakao/naver)",
        ),
        sa.Column(
            "social_id",
            sa.String(length=100),
            nullable=False,
            comment="소셜 PG 의 사용자 ID (모두 string 으로 저장)",
        ),
        sa.Column(
            "email_at_link",
            sa.String(length=255),
            nullable=True,
            comment="연결 시점 PG 가 알려준 이메일 (감사용 스냅샷)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="레코드 최초 생성 시각 (UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="마지막 수정 시각 (UPDATE 시 자동 갱신)",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "social_id", name="uq_social_provider_social_id"),
    )
    op.create_index(
        op.f("ix_social_accounts_user_id"),
        "social_accounts",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_social_accounts_user_id"), table_name="social_accounts")
    op.drop_table("social_accounts")
