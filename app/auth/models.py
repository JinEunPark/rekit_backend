import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Identity, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.user.models import User


class IdentityProvider(str, enum.Enum):
    """본인인증 PG. MVP 는 TOSS 사용 (결제 PG 와 동일 계약)."""

    TOSS = "TOSS"
    NICE = "NICE"
    KCB = "KCB"


class VerificationResult(str, enum.Enum):
    """인증 결과. FAIL 도 시도 로그로 보존(분쟁 대응)."""

    SUCCESS = "SUCCESS"
    FAIL = "FAIL"


class IdentityVerification(Base, TimestampMixin):
    """본인인증 시도 로그 — 분쟁 대응 / 감사용.

    User.identity_verified_at 은 SUCCESS 시점만 기록되지만,
    이 테이블은 FAIL/재시도까지 모두 추적한다.
    """

    __tablename__ = "identity_verifications"

    id: Mapped[int] = mapped_column(
        Identity(always=False),
        primary_key=True,
        comment="인증 시도 PK",
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="인증 시도 사용자 FK",
    )
    provider: Mapped[IdentityProvider] = mapped_column(
        Enum(IdentityProvider, native_enum=False, length=20),
        nullable=False,
        comment="인증 PG (TOSS/NICE/KCB)",
    )
    result: Mapped[VerificationResult] = mapped_column(
        Enum(VerificationResult, native_enum=False, length=10),
        nullable=False,
        comment="인증 결과 (SUCCESS/FAIL)",
    )
    request_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="PG 요청 식별자. 콜백 멱등성 보장 키 — 유니크 인덱스 추가 검토",
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="SUCCESS 시점. FAIL 이면 NULL",
    )
    fail_reason: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="FAIL 사유 (PG 에러 메시지). 사용자 노출 전 정제 필요",
    )

    user: Mapped["User"] = relationship(back_populates="identity_verifications")
