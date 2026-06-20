"""Toss Payments PG 어댑터 스텁.

MVP에서는 실제 HTTP 호출 대신 환경변수 기반 구현체로 교체 예정.
현재는 PaymentGateway Protocol을 만족하는 구조만 정의한다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

import httpx

from app.core.config import settings
from app.core.exceptions import PaymentFailed
from app.payment.adapters.ports import PaymentGateway, TossConfirmResult

_TOSS_CONFIRM_URL = "https://api.tosspayments.com/v1/payments/confirm"


class TossPaymentGateway:
    """Toss Payments REST API 어댑터. PaymentGateway Protocol 구현체."""

    async def confirm(
        self,
        *,
        payment_key: str,
        order_id: str,
        amount: int,
    ) -> TossConfirmResult:
        secret_key = getattr(settings, "toss_secret_key", "") or ""
        if not secret_key:
            raise PaymentFailed("Toss secret key가 설정되지 않았습니다.")

        encoded = base64.b64encode(f"{secret_key}:".encode()).decode()
        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
        }
        payload = {
            "paymentKey": payment_key,
            "orderId": order_id,
            "amount": amount,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_TOSS_CONFIRM_URL, json=payload, headers=headers)

        if resp.status_code != 200:
            raise PaymentFailed(f"Toss confirm 실패: {resp.status_code}")

        data = resp.json()
        card = data.get("card") or {}
        from datetime import datetime
        return TossConfirmResult(
            method=data.get("method", ""),
            pg_tid=payment_key,
            paid_at=datetime.fromisoformat(data["approvedAt"].replace("Z", "+00:00")),
            card_company=card.get("issuerCode"),
            card_last4=card.get("number", "")[-4:] or None,
            installment_months=card.get("installmentPlanMonths", 0),
            approval_number=card.get("approveNo"),
        )

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        secret_key = getattr(settings, "toss_secret_key", "") or ""
        if not secret_key:
            return False
        expected = hmac.new(
            secret_key.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
