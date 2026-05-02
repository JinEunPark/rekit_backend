import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Identity, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.order import Order


class ShipmentMethod(str, enum.Enum):
    """배송 방식. 무게/사이즈/지역에 따라 다르게 선택된다."""

    PARCEL = "PARCEL"  # 일반 택배 (소형 가전: 전자레인지/청소기 등)
    FREIGHT = "FREIGHT"  # 화물 택배 (대형: 냉장고/세탁기/에어컨)
    DIRECT = "DIRECT"  # 직접 배송 (서울/경기 한정, 철거 차량으로 운반)


class ShipmentStatus(str, enum.Enum):
    """배송 상태. 송장 입력 시 IN_TRANSIT 자동 전환, 추적 API 가 DELIVERED 갱신."""

    PREPARING = "PREPARING"  # 송장 미입력
    IN_TRANSIT = "IN_TRANSIT"  # 배송중
    DELIVERED = "DELIVERED"  # 배송 완료


class Shipment(Base, TimestampMixin):
    """배송 정보. 주문당 1건 (1:1) — uniqueConstraint(order_id).

    - PARCEL/FREIGHT: 송장번호 + 택배사 → 스마트택배 API 로 추적
    - DIRECT: 송장 없음, 운영자가 수동으로 status 갱신
    """

    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(
        Identity(always=False),
        primary_key=True,
        comment="배송 PK",
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        comment="주문 FK (1:1). 주문 삭제 시 cascade",
    )

    method: Mapped[ShipmentMethod] = mapped_column(
        Enum(ShipmentMethod, native_enum=False, length=20),
        default=ShipmentMethod.PARCEL,
        nullable=False,
        comment="배송 방식. Order.shipping_method 와 동기화 유지",
    )
    carrier: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="택배사명 (CJ대한통운, 한진택배 등). DIRECT 면 NULL",
    )
    tracking_number: Mapped[str | None] = mapped_column(
        String(50),
        index=True,
        nullable=True,
        comment="송장번호. 입력 시 IN_TRANSIT 자동 전환 트리거. DIRECT 면 NULL",
    )

    status: Mapped[ShipmentStatus] = mapped_column(
        Enum(ShipmentStatus, native_enum=False, length=20),
        default=ShipmentStatus.PREPARING,
        nullable=False,
        comment="배송 상태. 추적 API 폴링 결과로 DELIVERED 갱신",
    )
    shipped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="발송(IN_TRANSIT 전환) 시각",
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="수령 시각. 환불 윈도우(7일) 계산 기준",
    )
    last_tracked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="배송 추적 API 마지막 폴링 시각. Redis 캐시 무효화 기준",
    )

    order: Mapped["Order"] = relationship(back_populates="shipment")
