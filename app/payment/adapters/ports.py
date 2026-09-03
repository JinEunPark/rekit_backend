"""payment 모듈 어댑터 ports — TossPayments 연동 데이터 클래스 + Protocol.

PaymentService 는 이 Protocol 에만 의존한다. 구체 PG 구현체는
`app/payment/adapters/<provider>.py` 에 두고 deps.py 에서 와이어링.

기존 `app/payment/ports.py` 는 PaymentInitResult/PaymentVerifyResult/PaymentGateway 정의
(더 넓은 interface). 이 파일은 Toss confirm/조회 플로우 특화 데이터 클래스 + 단순화 Protocol 이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class TossConfirmResult:
    """PG confirm 결과. gateway.confirm() 이 반환하는 DTO."""

    method: str  # "카드" / "가상계좌" 등 PG 반환 문자열
    pg_tid: str  # PG 거래 ID (tosspayments 의 paymentKey)
    paid_at: datetime
    card_company: str | None  # 카드사명 (예: "신한카드")
    card_last4: str | None  # 카드 끝 4자리
    installment_months: int  # 0=일시불
    approval_number: str | None


@dataclass
class TossPaymentResult:
    """PG 결제 조회(GET /v1/payments) 결과.

    토스 결제 웹훅에는 서명이 없어서 body 를 신뢰할 수 없다.
    웹훅 수신 시 이 조회 결과로 **실제 결제 상태를 재확인**한다.
    """

    # READY / IN_PROGRESS / WAITING_FOR_DEPOSIT / DONE
    # / CANCELED / PARTIAL_CANCELED / ABORTED / EXPIRED
    status: str
    method: str
    pg_tid: str
    total_amount: int
    balance_amount: int  # 취소 가능 잔액. 0 이면 전액 취소된 상태
    approved_at: datetime | None
    card_company: str | None
    card_last4: str | None
    installment_months: int
    approval_number: str | None


class PaymentGateway(Protocol):
    """PG 어댑터 인터페이스. Toss / PortOne / KG이니시스 교체 가능."""

    async def confirm(
        self,
        *,
        payment_key: str,
        order_id: str,  # order_number (toss 가 orderId 로 부름)
        amount: int,
    ) -> TossConfirmResult:
        """결제 confirm. 프론트 성공 콜백 후 서버↔PG 검증."""
        ...

    async def get_payment(self, *, payment_key: str) -> TossPaymentResult:
        """결제 단건 조회. 웹훅 수신 후 실제 상태를 재확인할 때 사용.

        조회 자체에 실패하면(네트워크/5xx) PaymentGatewayUnknownError 를 던진다 —
        상태 불명이므로 웹훅을 재시도시켜야 한다.
        """
        ...
