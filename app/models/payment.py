import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Identity, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.order import Order


class PgProvider(str, enum.Enum):
    TOSS = "TOSS"
    KAKAO = "KAKAO"
    NAVER = "NAVER"


class PaymentMethod(str, enum.Enum):
    CARD = "CARD"
    BANK = "BANK"
    KAKAO_PAY = "KAKAO_PAY"
    NAVER_PAY = "NAVER_PAY"
    TOSS_PAY = "TOSS_PAY"


class PaymentStatus(str, enum.Enum):
    READY = "READY"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    PARTIAL_CANCELLED = "PARTIAL_CANCELLED"
    FAILED = "FAILED"


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Identity(always=False), primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    pg_provider: Mapped[PgProvider] = mapped_column(
        Enum(PgProvider, native_enum=False, length=20), nullable=False
    )
    pg_tid: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, native_enum=False, length=20), nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False, length=20),
        default=PaymentStatus.READY,
        nullable=False,
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fail_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    card_company: Mapped[str | None] = mapped_column(String(30), nullable=True)
    card_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    installment_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approval_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    order: Mapped["Order"] = relationship(back_populates="payments")
