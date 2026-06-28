from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Identity, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.user.models import User


class Address(Base, TimestampMixin):
    """배송지(주소록) — 사용자당 N개. 주문 생성 시점에 Order 로 스냅샷 복사된다.

    - 한 사용자에 여러 배송지를 둘 수 있고, `is_default=True` 인 한 건이 기본 배송지.
    - 주문 후 주소가 바뀌어도 Order 의 recipient/zipcode/address 컬럼은 변경되지 않음(스냅샷).
    """

    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(
        Identity(always=False),
        primary_key=True,
        comment="배송지 PK",
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="소유 사용자 FK (회원 탈퇴 시 cascade 삭제)",
    )
    recipient: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="수령인 이름",
    )
    phone: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="수령인 연락처 (배송 안내용)",
    )
    zipcode: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="우편번호 5자리 (직배송 가능 지역 판정에 사용)",
    )
    address1: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="기본 주소 (도로명/지번)",
    )
    address2: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="상세 주소 (동·호수 등)",
    )
    label: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        comment="배송지 별칭 (예: 집, 회사)",
    )
    memo: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="배송 메모 (예: 경비실 앞 놔주세요)",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="기본 배송지 여부 — 사용자별 1건만 true 가 되도록 서비스 레이어에서 보장",
    )

    user: Mapped["User"] = relationship(back_populates="addresses")
