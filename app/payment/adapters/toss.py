"""Toss Payments PG 어댑터.

`PaymentGateway` Protocol 구현체. 토스페이먼츠 코어 API(REST)를 직접 호출한다.
- confirm: POST /v1/payments/confirm — 프론트 성공 콜백 후 서버 승인
- get_payment: GET /v1/payments/{paymentKey} — 웹훅 수신 후 실제 상태 재확인

인증은 시크릿 키 Basic 인증(`base64(secretKey + ":")`) — `settings.toss_secret_key`.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import NoReturn

import httpx

from app.core.config import settings
from app.core.exceptions import PaymentFailedError, PaymentGatewayUnknownError
from app.payment.adapters.ports import (
    TossCancelResult,
    TossConfirmResult,
    TossPaymentResult,
)

_TOSS_API_BASE = "https://api.tosspayments.com/v1/payments"
_TOSS_CONFIRM_URL = f"{_TOSS_API_BASE}/confirm"
_HTTP_TIMEOUT = 10.0


def _raise_toss_failure(resp: httpx.Response, prefix: str) -> NoReturn:
    """토스 에러 응답 body 의 {code, message} 를 PaymentFailedError 로 변환."""
    code = ""
    message = ""
    try:
        body = resp.json()
        if isinstance(body, dict):
            code = str(body.get("code") or "")
            message = str(body.get("message") or "")
    except ValueError:
        pass
    detail = f"{code}: {message}" if code else f"HTTP {resp.status_code}"
    raise PaymentFailedError(f"{prefix} — {detail}")


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
        # 즉시 승인되는 수단만 취급한다 (카드/간편결제/실시간계좌이체 → DONE).
        # 가상계좌는 WAITING_FOR_DEPOSIT 로 오는데, 이걸 PAID 로 처리하면 입금 전에
        # 주문이 확정되는 버그가 된다. MVP 는 가상계좌 미지원 → DONE 아니면 거절.
        remote_status = data.get("status")
        if remote_status != "DONE":
            raise PaymentFailedError(f"Toss confirm 결과가 DONE 이 아님: {remote_status}")

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

    async def cancel(
        self,
        *,
        payment_key: str,
        reason: str,
        cancel_amount: int | None = None,
    ) -> TossCancelResult:
        headers = {
            **_auth_header(),
            "Content-Type": "application/json",
            # 네트워크 재시도로 인한 이중 취소 방지. 전액 취소는 재시도해도 멱등.
            "Idempotency-Key": f"cancel-{payment_key}-{cancel_amount or 'full'}",
        }
        payload: dict[str, object] = {"cancelReason": reason}
        if cancel_amount is not None:
            payload["cancelAmount"] = cancel_amount
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(
                    f"{_TOSS_API_BASE}/{payment_key}/cancel",
                    json=payload,
                    headers=headers,
                )
        except httpx.TransportError as exc:
            # 취소 성공 여부 불명 — 재조회로 확인해야 함. PaymentFailedError 와 구분.
            raise PaymentGatewayUnknownError() from exc

        if resp.status_code != 200:
            _raise_toss_failure(resp, "Toss 결제 취소 실패")

        data = resp.json()
        cancels = data.get("cancels") or []
        latest = cancels[-1] if cancels else {}
        return TossCancelResult(
            status=data.get("status", ""),
            cancelled_amount=latest.get("cancelAmount", cancel_amount or 0) or 0,
            balance_amount=data.get("balanceAmount", 0) or 0,
            transaction_key=latest.get("transactionKey"),
        )
