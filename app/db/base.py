from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative 베이스. 모든 모델의 부모."""

    pass


class TimestampMixin:
    """생성/수정 시각 자동 기록 믹스인. JPA의 @CreatedDate / @LastModifiedDate 와 동일 역할."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="레코드 최초 생성 시각 (UTC, DB 기본값으로 자동 채움)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="마지막 수정 시각 (UPDATE 시 자동 갱신)",
    )
