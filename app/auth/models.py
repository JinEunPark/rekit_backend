import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Identity, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.user.models import User


class SocialProvider(str, enum.Enum):
    """소셜 로그인 PG. lowercase 유지 — URL 경로 / OAuth client 설정과 그대로 매칭."""

    KAKAO = "kakao"
    NAVER = "naver"
    GOOGLE = "google"


class SocialAccount(Base, TimestampMixin):
    """소셜 로그인 연결 — User 1 : N SocialAccount.

    한 User 가 카카오 + 네이버 등 여러 provider 를 동시에 연결 가능. provider 별로
    social_id 는 유니크 (= 동일 카카오 계정으로 다른 rekit User 에 중복 연결 차단).
    """

    __tablename__ = "social_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "social_id", name="uq_social_provider_social_id"),
    )

    id: Mapped[int] = mapped_column(
        Identity(always=False),
        primary_key=True,
        comment="소셜 연결 PK",
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="연결된 rekit User FK. 회원 탈퇴 시 cascade 정리",
    )
    provider: Mapped[SocialProvider] = mapped_column(
        Enum(SocialProvider, native_enum=False, length=20),
        nullable=False,
        comment="소셜 PG (kakao/naver)",
    )
    social_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="소셜 PG 의 사용자 ID (카카오는 long, 네이버는 string — 모두 string 으로 저장)",
    )
    email_at_link: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="연결 시점에 PG 가 알려준 이메일 (감사용 스냅샷). 사용자가 PG 측에서 변경해도 이 값은 고정",
    )

    user: Mapped["User"] = relationship(back_populates="social_accounts")


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
