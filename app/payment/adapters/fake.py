"""개발용 Fake PG 어댑터 — 실제 PG 없이 결제가 항상 성공한다.

USE_FAKE_PG=true 환경변수로 활성화. 운영 환경에서는 절대 사용 금지.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.payment.adapters.ports import PaymentGateway, TossConfirmResult


class FakePaymentGateway:
    """결제가 항상 성공하는 개발용 구현체. PaymentGateway Protocol 만족."""

    async def confirm(
        self,
        *,
        payment_key: str,
        order_id: str,
        amount: int,
    ) -> TossConfirmResult:
        return TossConfirmResult(
            method="CARD",
            pg_tid=payment_key,
            paid_at=datetime.now(UTC),
            card_company="개발카드",
            card_last4="0000",
            installment_months=0,
            approval_number="FAKE-APPROVAL",
        )

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        return True


# Protocol 정합성 체크 (import 시점에 검증)
_: PaymentGateway = FakePaymentGateway()
