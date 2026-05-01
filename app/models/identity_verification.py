import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Identity, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class IdentityProvider(str, enum.Enum):
    TOSS = "TOSS"
    NICE = "NICE"
    KCB = "KCB"


class VerificationResult(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"


class IdentityVerification(Base, TimestampMixin):
    """본인인증 시도 로그 — 분쟁 대응 / 감사용."""

    __tablename__ = "identity_verifications"

    id: Mapped[int] = mapped_column(Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[IdentityProvider] = mapped_column(
        Enum(IdentityProvider, native_enum=False, length=20), nullable=False
    )
    result: Mapped[VerificationResult] = mapped_column(
        Enum(VerificationResult, native_enum=False, length=10), nullable=False
    )
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fail_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User"] = relationship(back_populates="identity_verifications")
