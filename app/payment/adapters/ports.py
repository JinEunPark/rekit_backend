"""payment 모듈 어댑터 ports — TossPayments confirm 결과 데이터 클래스 + Protocol.

PaymentService 는 이 Protocol 에만 의존한다. 구체 PG 구현체는
`app/payment/adapters/<provider>.py` 에 두고 deps.py 에서 와이어링.

기존 `app/payment/ports.py` 는 PaymentInitResult/PaymentVerifyResult/PaymentGateway 정의
(더 넓은 interface). 이 파일은 Toss confirm 플로우 특화 데이터 클래스 + 단순화 Protocol 이다.
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

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        """PG webhook X-Signature HMAC 검증. 위변조 차단."""
        ...
