"""rename_username_to_login_id_and_name_to_username

Revision ID: c1a4d8e2f6b3
Revises: 589d381b3893
Create Date: 2026-05-06 22:30:00.000000+09:00

명명 정리:
- users.username → users.login_id  (로그인 아이디)
- users.name     → users.username  (사용자 이름, 표시용 — NOT NULL 로 변경)
- 인덱스 ix_users_username → ix_users_login_id

가입 화면에서 이름(username) 을 직접 입력받기로 결정 → username NOT NULL 강제.
주의: dev DB 가정 (rename 시 기존 NULL row 가 있으면 NOT NULL 변경이 실패).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1a4d8e2f6b3"
down_revision: str | None = "589d381b3893"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. users.username (로그인용) → login_id
    op.alter_column(
        "users",
        "username",
        new_column_name="login_id",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        comment="로그인 아이디. ^[a-zA-Z0-9_]{4,20}$. 회원가입 시 입력",
    )
    # 인덱스 이름도 동기화 (Postgres 는 인덱스명 별도 — rename 안 하면 DB 와 모델 어긋남)
    op.execute("ALTER INDEX ix_users_username RENAME TO ix_users_login_id")

    # 2. users.name (이름) → username, 동시에 NOT NULL 로
    op.alter_column(
        "users",
        "name",
        new_column_name="username",
        existing_type=sa.String(length=50),
        nullable=False,  # NOT NULL 강제 — 가입 시 필수 입력으로 정책 변경
        comment="사용자 이름 (표시용). 회원가입 시 입력. 본인인증 후 인증 결과로 갱신 가능",
        existing_comment="표시용 이름. 가입 화면엔 입력란 없음 → 본인인증 후 인증 결과로 채움",
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "username",
        new_column_name="name",
        existing_type=sa.String(length=50),
        nullable=True,
        comment="표시용 이름. 가입 화면엔 입력란 없음 → 본인인증 후 인증 결과로 채움",
        existing_comment="사용자 이름 (표시용). 회원가입 시 입력. 본인인증 후 인증 결과로 갱신 가능",
    )
    op.execute("ALTER INDEX ix_users_login_id RENAME TO ix_users_username")
    op.alter_column(
        "users",
        "login_id",
        new_column_name="username",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        comment="로그인 아이디. ^[a-zA-Z0-9_]{4,20}$. 회원가입 시 입력",
    )
