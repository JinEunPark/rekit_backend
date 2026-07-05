import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Identity, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.order.shipment import ShipmentMethod

if TYPE_CHECKING:
    from app.order.shipment import Shipment
    from app.payment.models import Payment
    from app.user.models import User


class OrderStatus(enum.StrEnum):
    """주문 상태 흐름:

    PENDING → PAID → PREPARING → SHIPPING → DELIVERED
                                           ↘ CANCELLED / REFUNDED
    - PENDING: 주문 생성 직후, 결제 대기
    - PAID: 결제 confirm 성공
    - PREPARING: 운영자 송장 입력 전 준비 단계
    - SHIPPING: 송장 입력 시 자동 전환
    - DELIVERED: 배송 추적 완료 또는 운영자 수동 처리
    - CANCELLED: 결제 전 / 결제~준비중 취소
    - REFUNDED: 환불 완료 (PG 취소 호출 후)
    """

    PENDING = "PENDING"
    PAID = "PAID"
    PREPARING = "PREPARING"
    SHIPPING = "SHIPPING"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class Order(Base, TimestampMixin):
    """주문 헤더. 주소/금액은 주문 시점 스냅샷이 저장되며 이후 변경 불가.

    `order_number` 는 RK-YYMMDD#### 포맷의 사람이 읽는 식별자 (PK 와 별개).
    `total_amount = items.sum(price * qty) + shipping_fee - discount_amount`.
    """

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(
        Identity(always=False),
        primary_key=True,
        comment="주문 PK (내부용)",
    )
    order_number: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        index=True,
        nullable=False,
        comment="사람이 읽는 주문번호 (RK-YYMMDD####). 영수증/CS 식별자",
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
        comment="주문자 FK. 거래 정보 보존(5년) 의무로 RESTRICT — 회원 탈퇴 시에도 주문은 남김",
    )

    total_amount: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="최종 결제 금액(원) = 상품합 + 배송비 - 할인",
    )
    shipping_fee: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="배송비(원). 화물 60,000 / 직배송 40,000 / 일반택배는 무게 기반",
    )
    discount_amount: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="할인 금액(원). 직배송 선택 시 -20,000 등",
    )

    shipping_method: Mapped[ShipmentMethod] = mapped_column(
        Enum(ShipmentMethod, native_enum=False, length=20),
        nullable=False,
        comment="배송 방식. DIRECT 는 zipcode 가 서울/경기 prefix 일 때만 허용",
    )

    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, native_enum=False, length=20),
        default=OrderStatus.PENDING,
        index=True,
        nullable=False,
        comment="주문 상태. 관리자 탭 카운트와 사용자 마이페이지 카운트의 기준",
    )

    # ── 배송지 스냅샷 (주문 시점 Address 복사) ─────────────────
    recipient_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="수령인 이름 (스냅샷)",
    )
    recipient_phone: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="수령인 연락처 (스냅샷)",
    )
    zipcode: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="우편번호 (스냅샷)",
    )
    address1: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="기본 주소 (스냅샷)",
    )
    address2: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="상세 주소 (스냅샷)",
    )
    memo: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="배송 메모 (예: 부재 시 경비실)",
    )

    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="결제 완료 시각. PAID 전환 시 채움",
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="취소 시각. CANCELLED/REFUNDED 전환 시 채움",
    )

    user: Mapped["User"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(back_populates="order")
    shipment: Mapped["Shipment | None"] = relationship(
        back_populates="order", uselist=False, cascade="all, delete-orphan"
    )


class OrderItem(Base):
    """주문 상품 라인. 상품 정보는 모두 스냅샷 — Product 가 수정/삭제돼도 영수증 재현 가능."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(
        Identity(always=False),
        primary_key=True,
        comment="주문 라인 PK",
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="소속 주문 FK",
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        comment="원본 상품 FK. RESTRICT — 주문이 있는 상품은 삭제 차단",
    )

    # ── 주문 시점 스냅샷 (상품 변경/삭제에 안전) ─────────────
    product_title_snapshot: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="주문 당시 상품명 (스냅샷)",
    )
    product_brand_snapshot: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="주문 당시 브랜드명 (스냅샷). NULL 허용 — 브랜드 미입력 상품 대응",
    )
    product_model_name_snapshot: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="주문 당시 모델명 (스냅샷). NULL 허용 — 모델명 미입력 상품 대응",
    )
    product_image_url_snapshot: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="주문 당시 대표 이미지 URL (스냅샷). 주문내역/마이페이지 카드에 노출",
    )
    price_snapshot: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="주문 당시 판매가 (스냅샷). 가격 변동 후에도 결제 금액 재현 가능",
    )
    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="주문 수량",
    )

    order: Mapped[Order] = relationship(back_populates="items")
