import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, Identity, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.address.models import Address
    from app.auth.models import SocialAccount
    from app.cart.models import CartItem
    from app.order.models import Order


class UserRole(enum.StrEnum):
    """사용자 권한 등급. 관리자 라우터는 ADMIN 만 통과시킨다."""

    USER = "USER"
    ADMIN = "ADMIN"


class UserStatus(enum.StrEnum):
    """계정 상태. BANNED 는 로그인 차단, DORMANT 는 1년 무접속 휴면, WITHDRAWN 은 자발적 탈퇴."""

    ACTIVE = "ACTIVE"
    BANNED = "BANNED"
    DORMANT = "DORMANT"
    WITHDRAWN = "WITHDRAWN"


class User(Base, TimestampMixin):
    """플랫폼 사용자(구매자/관리자 통합 테이블).

    인증 단계는 2가지로 나뉜다 (요구사항정의서 §2.4):
    - 1차 휴대폰 인증(Octomo) — 회원가입 후 언제든 1회, `phone_verified_at` 기록.
      첫 주문 전 재인증을 요구하지 않는다 — 이 하나가 곧 `User.verified` 기준.
    - 2차 카드 본인확인 — PG 가 처리, 우리 DB 에는 저장 X

    (과거 CI/DI 기반 본인인증은 법적 의무가 아니고 신뢰 가능한 대체 수단도
    없어 폐기함 — Octomo 전화번호 인증으로 대체.)
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Identity(always=False),
        primary_key=True,
        comment="사용자 PK",
    )
    login_id: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        index=True,
        nullable=False,
        comment="로그인 아이디. ^[a-zA-Z0-9_]{4,20}$. 회원가입 시 입력",
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
        comment="이메일. 비번찾기 등 본인확인용. 소문자 정규화는 서비스 레이어에서",
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="bcrypt 해시값. 평문/SHA 류는 절대 저장 금지",
    )
    username: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="사용자 이름 (표시용). 회원가입 시 입력. 본인인증 후 인증 결과로 갱신 가능",
    )
    phone: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="휴대폰 번호 (010-0000-0000 형식으로 정규화). SMS 인증 후에만 신뢰 가능",
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=20),
        default=UserRole.USER,
        nullable=False,
        comment="권한 등급 (USER/ADMIN). 관리자 API 가드의 기준",
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, native_enum=False, length=20),
        default=UserStatus.ACTIVE,
        server_default="ACTIVE",
        nullable=False,
        comment="계정 상태. BANNED → 로그인 차단. is_active 와 동기화 유지",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="활성 여부. status=ACTIVE ↔ is_active=True 로 동기화",
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        comment=(
            "임시 비밀번호로 발급된 상태인지 여부. "
            "find-password 로 임시 비번 발급 시 True, 사용자가 새 비번 설정 시 False. "
            "True 동안엔 비번 변경 외 다른 endpoint 가 인증 가드에서 차단된다."
        ),
    )

    # ── 약관 동의 시각 (전자상거래법 — 동의 시각 보존 의무) ─────
    # bool 컬럼 대신 timestamp 로 둬서 "언제 동의했는지" 가 자동 보존됨.
    # 약관 개정 시 이 컬럼들 < 약관.published_at 인 사용자에게 재동의 받는 패턴.
    agreed_terms_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="이용약관 동의 시각 (필수). 회원가입 시점에 기록",
    )
    agreed_privacy_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="개인정보 수집·이용 동의 시각 (필수)",
    )
    agreed_marketing_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="마케팅 정보 수신 동의 시각 (선택). 미동의면 NULL",
    )

    # ── 휴대폰 인증 (Octomo) — 1차/2차 통합, 회원가입 후 언제든 1회 ─────
    phone_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="휴대폰 인증(Octomo) 통과 시각. NULL 이면 미인증 — User.verified 의 유일한 기준",
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="회원탈퇴 처리 시각. NULL 이면 활성 계정",
    )

    addresses: Mapped[list["Address"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    cart_items: Mapped[list["CartItem"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    social_accounts: Mapped[list["SocialAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def verified(self) -> bool:
        """휴대폰 인증(Octomo) 통과 여부. 응답 DTO 가 `from_attributes` 로 가져간다."""
        return self.phone_verified_at is not None
