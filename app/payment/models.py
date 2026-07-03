import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Identity, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.order.models import Order


class PgProvider(enum.StrEnum):
    """결제 PG. MVP 는 TOSS 단일 계약."""

    TOSS = "TOSS"
    KAKAO = "KAKAO"
    NAVER = "NAVER"


class PaymentMethod(enum.StrEnum):
    """결제 수단. 매출 분석에서 5종으로 집계된다.

    주문서 화면은 3개 그룹(신용카드/계좌이체/간편결제)으로 묶이며,
    간편결제는 KAKAO_PAY/NAVER_PAY/TOSS_PAY 로 분기.
    """

    CARD = "CARD"
    BANK = "BANK"
    KAKAO_PAY = "KAKAO_PAY"
    NAVER_PAY = "NAVER_PAY"
    TOSS_PAY = "TOSS_PAY"


class PaymentStatus(enum.StrEnum):
    """결제 상태. webhook 멱등성 처리의 기준."""

    READY = "READY"  # 결제창 발급, 사용자 입력 대기
    PAID = "PAID"  # confirm 성공
    CANCELLED = "CANCELLED"  # 전액 취소
    PARTIAL_CANCELLED = "PARTIAL_CANCELLED"  # 부분 취소(환불)
    FAILED = "FAILED"  # 사용자 입력 후 PG 거절


class Payment(Base, TimestampMixin):
    """결제 트랜잭션.

    PCI-DSS 준수:
    - 토스 결제창은 브라우저 ↔ PG 직통 전송이라 카드 PAN 이 우리 서버를 통과하지 않음.
    - 따라서 SAQ-A 수준만 충족하면 되고, 아래 메타데이터만 저장한다.
    - 절대 저장 금지: 카드 PAN(전체번호), CVC/CVV, 유효기간(단독 저장).
    - 저장 OK: 카드사명, last4, 할부 개월, 승인번호, PG 거래ID.

    `pg_tid` 유니크 제약은 결제 confirm/webhook 의 멱등성 키.
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(
        Identity(always=False),
        primary_key=True,
        comment="결제 PK",
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
        comment="결제 대상 주문 FK. 결제가 있는 주문은 삭제 차단",
    )
    pg_provider: Mapped[PgProvider] = mapped_column(
        Enum(PgProvider, native_enum=False, length=20),
        nullable=False,
        comment="결제 PG (TOSS/KAKAO/NAVER)",
    )
    pg_tid: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
        comment="PG 거래 ID. 멱등성 키 — webhook 중복 호출 방어용 unique 제약",
    )
    method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, native_enum=False, length=20),
        nullable=False,
        comment="결제 수단 (CARD/BANK/KAKAO_PAY/NAVER_PAY/TOSS_PAY)",
    )
    amount: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="결제 금액(원). Order.total_amount 와 일치해야 함",
    )
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False, length=20),
        default=PaymentStatus.READY,
        nullable=False,
        comment="결제 상태. webhook 처리의 멱등성 기준",
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="PG 승인 시각",
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="취소/환불 시각",
    )
    fail_reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="실패 사유 (PG 에러 메시지). 사용자 노출 전 정제 필요",
    )

    # ── 영수증 / 환불용 메타데이터 (PCI-DSS 안전 범위) ─────────
    card_company: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        comment="카드 발급사 (예: '신한카드'). 영수증 표시용 — PCI-DSS 안전",
    )
    card_last4: Mapped[str | None] = mapped_column(
        String(4),
        nullable=True,
        comment="카드 끝 4자리. PCI-DSS 가 명시 허용 (first6+last4 까지 OK)",
    )
    installment_months: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="할부 개월 (0=일시불, 2~12=할부)",
    )
    approval_number: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="카드 승인번호. 환불/취소 호출 시 PG 가 요구",
    )

    order: Mapped["Order"] = relationship(back_populates="payments")
