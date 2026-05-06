"""add_username_and_consent_timestamps

Revision ID: 589d381b3893
Revises: 6ae8f19a3e0f
Create Date: 2026-05-06 22:04:01.614492+09:00

users 테이블 변경:
- 추가: username (UNIQUE, INDEX, NOT NULL, 20자) — 로그인 아이디
- 추가: agreed_terms_at, agreed_privacy_at (NOT NULL, timestamptz) — 필수 약관
- 추가: agreed_marketing_at (nullable, timestamptz) — 선택 약관
- 변경: name 을 NOT NULL → nullable (가입 화면에 입력란 없음)

주의: NOT NULL 컬럼 추가는 기존 데이터가 있으면 실패한다. 운영 환경에선 단계적
      마이그레이션(server_default → backfill → drop default) 이 필요하지만, 본
      마이그레이션은 dev 환경(데이터 없음) 가정.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "589d381b3893"
down_revision: str | None = "6ae8f19a3e0f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. username 컬럼 추가 (NOT NULL → 기존 row 가 있으면 실패. dev 가정).
    op.add_column(
        "users",
        sa.Column(
            "username",
            sa.String(length=20),
            nullable=False,
            comment="로그인 아이디. ^[a-zA-Z0-9_]{4,20}$. 회원가입 시 입력",
        ),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    # 2. 약관 동의 시각 컬럼 3개 (필수 2 + 선택 1).
    op.add_column(
        "users",
        sa.Column(
            "agreed_terms_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="이용약관 동의 시각 (필수). 회원가입 시점에 기록",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "agreed_privacy_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="개인정보 수집·이용 동의 시각 (필수)",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "agreed_marketing_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="마케팅 정보 수신 동의 시각 (선택). 미동의면 NULL",
        ),
    )

    # 3. name 을 nullable 로. 회원가입 화면에 이름 입력란이 없어 본인인증 후에 채움.
    op.alter_column(
        "users",
        "name",
        existing_type=sa.VARCHAR(length=50),
        nullable=True,
        comment="표시용 이름. 가입 화면엔 입력란 없음 → 본인인증 후 인증 결과로 채움",
        existing_comment="표시용 이름. 본인인증 후에는 인증 결과로 덮어쓰기 권장",
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "name",
        existing_type=sa.VARCHAR(length=50),
        nullable=False,
        comment="표시용 이름. 본인인증 후에는 인증 결과로 덮어쓰기 권장",
        existing_comment="표시용 이름. 가입 화면엔 입력란 없음 → 본인인증 후 인증 결과로 채움",
    )
    op.drop_column("users", "agreed_marketing_at")
    op.drop_column("users", "agreed_privacy_at")
    op.drop_column("users", "agreed_terms_at")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_column("users", "username")
