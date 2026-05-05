"""payment 모듈의 외부 통합 ports.

PaymentService 는 PG SDK 를 직접 import 하지 않고 이 Protocol 에만 의존한다.
구현체는 `app.payment.adapters.<provider>.py` 에 두고,
와이어링은 `app.core.deps` 에서 한다 (예: `Depends(get_payment_gateway)`).

JPA 비유: PaymentGateway 가 인터페이스, TosspaymentsAdapter 가 @Service 빈,
와이어링이 @Configuration. Spring 의 @Qualifier 대신 deps.py 에서 직접 선택.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PaymentInitResult:
    """PG 결제창 초기화 결과 — 클라이언트 SDK 가 이 데이터로 결제 위젯을 띄운다."""

    payment_key: str
    amount: int
    order_id: str
    success_url: str
    fail_url: str
    pg_provider: str  # "tosspayments" 등


@dataclass(frozen=True)
class PaymentVerifyResult:
    """PG confirm 응답 — 멱등성 키(pg_tid)와 영수증 메타데이터."""

    pg_tid: str
    paid_amount: int
    method: str  # CARD / BANK / KAKAO_PAY ...
    card_company: str | None
    card_last4: str | None
    installment_months: int | None
    approval_number: str | None


class PaymentGateway(Protocol):
    """결제 PG 어댑터 인터페이스. Toss/PortOne/KG이니시스 구현체를 갈아끼울 수 있다."""

    async def init_payment(
        self,
        order_id: str,
        amount: int,
        method: str,
    ) -> PaymentInitResult:
        """결제창 발급. 사용자가 위젯에서 입력 시작 직전 단계."""
        ...

    async def verify(
        self,
        payment_key: str,
        order_id: str,
        amount: int,
    ) -> PaymentVerifyResult:
        """결제 confirm. 위젯 success redirect 후 서버↔PG 검증.

        amount 불일치 시 예외. 멱등성: pg_tid 가 같으면 같은 결제.
        """
        ...

    async def cancel(self, pg_tid: str, amount: int | None = None) -> None:
        """전액(amount=None) 또는 부분 취소. 환불 처리."""
        ...

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """PG webhook X-Signature 검증. 위변조 차단."""
        ...
