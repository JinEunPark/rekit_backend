import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Identity, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.user.models import User


class SocialProvider(enum.StrEnum):
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
        comment=(
            "연결 시점에 PG 가 알려준 이메일 (감사용 스냅샷). "
            "사용자가 PG 측에서 변경해도 이 값은 고정"
        ),
    )

    user: Mapped["User"] = relationship(back_populates="social_accounts")
