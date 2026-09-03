"""Toss Payments PG 어댑터.

`PaymentGateway` Protocol 구현체. 토스페이먼츠 코어 API(REST)를 직접 호출한다.
- confirm: POST /v1/payments/confirm — 프론트 성공 콜백 후 서버 승인
- get_payment: GET /v1/payments/{paymentKey} — 웹훅 수신 후 실제 상태 재확인

인증은 시크릿 키 Basic 인증(`base64(secretKey + ":")`).
`USE_FAKE_PG=true` 면 이 클래스 대신 FakePaymentGateway 가 주입된다 (deps.py).
"""

from __future__ import annotations

import base64
from datetime import datetime

import httpx

from app.core.config import settings
from app.core.exceptions import PaymentFailedError, PaymentGatewayUnknownError
from app.payment.adapters.ports import TossConfirmResult, TossPaymentResult

_TOSS_API_BASE = "https://api.tosspayments.com/v1/payments"
_TOSS_CONFIRM_URL = f"{_TOSS_API_BASE}/confirm"
_HTTP_TIMEOUT = 10.0


def _auth_header() -> dict[str, str]:
    """토스 Basic 인증 헤더. 시크릿 키 뒤에 콜론을 붙여 base64 인코딩한다."""
    secret_key = settings.toss_secret_key or ""
    if not secret_key:
        raise PaymentFailedError("Toss secret key가 설정되지 않았습니다.")
    encoded = base64.b64encode(f"{secret_key}:".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def _parse_toss_datetime(raw: str | None) -> datetime | None:
    """토스 ISO-8601 타임스탬프(`2026-07-06T12:00:00+09:00`)를 tz-aware datetime 으로."""
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _card_last4(card: dict[str, object]) -> str | None:
    number = str(card.get("number") or "")
    return number[-4:] or None


class TossPaymentGateway:
    """Toss Payments REST API 어댑터. PaymentGateway Protocol 구현체."""

    async def confirm(
        self,
        *,
        payment_key: str,
        order_id: str,
        amount: int,
    ) -> TossConfirmResult:
        headers = {**_auth_header(), "Content-Type": "application/json"}
        payload = {
            "paymentKey": payment_key,
            "orderId": order_id,
            "amount": amount,
        }
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(_TOSS_CONFIRM_URL, json=payload, headers=headers)
        except httpx.TransportError as exc:
            # 타임아웃/커넥션 에러 — 결제 성공 여부 불명. PaymentFailedError와 구분.
            raise PaymentGatewayUnknownError() from exc

        if resp.status_code != 200:
            raise PaymentFailedError(f"Toss confirm 실패: {resp.status_code}")

        data = resp.json()
        card = data.get("card") or {}
        approved_at = _parse_toss_datetime(data.get("approvedAt"))
        if approved_at is None:
            raise PaymentFailedError("Toss confirm 응답에 approvedAt 이 없습니다.")
        return TossConfirmResult(
            method=data.get("method", ""),
            pg_tid=payment_key,
            paid_at=approved_at,
            card_company=card.get("issuerCode"),
            card_last4=_card_last4(card),
            installment_months=card.get("installmentPlanMonths", 0) or 0,
            approval_number=card.get("approveNo"),
        )

    async def get_payment(self, *, payment_key: str) -> TossPaymentResult:
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(
                    f"{_TOSS_API_BASE}/{payment_key}", headers=_auth_header()
                )
        except httpx.TransportError as exc:
            raise PaymentGatewayUnknownError() from exc

        if resp.status_code != 200:
            # 조회 실패 — 상태 불명. 웹훅을 재시도시켜야 하므로 Unknown 으로.
            raise PaymentGatewayUnknownError()

        data = resp.json()
        card = data.get("card") or {}
        return TossPaymentResult(
            status=data.get("status", ""),
            method=data.get("method", ""),
            pg_tid=data.get("paymentKey") or payment_key,
            total_amount=data.get("totalAmount", 0) or 0,
            balance_amount=data.get("balanceAmount", 0) or 0,
            approved_at=_parse_toss_datetime(data.get("approvedAt")),
            card_company=card.get("issuerCode"),
            card_last4=_card_last4(card),
            installment_months=card.get("installmentPlanMonths", 0) or 0,
            approval_number=card.get("approveNo"),
        )
