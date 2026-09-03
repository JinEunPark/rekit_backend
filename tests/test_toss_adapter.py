"""TossPaymentGateway 어댑터 단위 테스트.

실제 네트워크 호출 없이 httpx.AsyncClient를 mock으로 교체하여 검증.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.exceptions import PaymentFailedError, PaymentGatewayUnknownError
from app.payment.adapters.toss import TossPaymentGateway


def _make_gateway() -> TossPaymentGateway:
    return TossPaymentGateway()


def _mock_200_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "status": "DONE",
        "method": "카드",
        "approvedAt": "2026-07-06T12:00:00+09:00",
        "card": {
            "issuerCode": "신한카드",
            "number": "1234567890001234",
            "installmentPlanMonths": 0,
            "approveNo": "12345678",
        },
    }
    return resp


def _mock_4xx_response(status_code: int = 400) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    return resp


async def test_confirm_200_response_parses_result_correctly() -> None:
    """200 응답을 올바르게 파싱해서 TossConfirmResult를 반환한다."""
    gateway = _make_gateway()
    mock_resp = _mock_200_response()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.toss_secret_key = "test_secret"
        result = await gateway.confirm(
            payment_key="toss_key_abc",
            order_id="RK-2606200001",
            amount=300_000,
        )

    assert result.pg_tid == "toss_key_abc"
    assert result.card_company == "신한카드"
    assert result.card_last4 == "1234"
    assert result.installment_months == 0
    assert result.approval_number == "12345678"
    assert isinstance(result.paid_at, datetime)


async def test_confirm_200_response_no_card_info_returns_none_for_card_last4() -> None:
    """card 정보 없을 때(간편결제 등) card_last4가 None으로 반환된다."""
    gateway = _make_gateway()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "status": "DONE",
        "method": "간편결제",
        "approvedAt": "2026-07-06T12:00:00+09:00",
        # card 키 없음
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=resp)

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.toss_secret_key = "test_secret"
        result = await gateway.confirm(
            payment_key="k", order_id="RK-1", amount=100_000
        )

    assert result.card_last4 is None


async def test_confirm_non_done_status_raises_payment_failed() -> None:
    """가상계좌 등 즉시 승인이 아닌 응답(status != DONE)은 거절한다 (입금 전 확정 방지)."""
    gateway = _make_gateway()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "status": "WAITING_FOR_DEPOSIT",
        "method": "가상계좌",
        "approvedAt": None,
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=resp)

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.toss_secret_key = "test_secret"
        with pytest.raises(PaymentFailedError, match="DONE"):
            await gateway.confirm(payment_key="k", order_id="RK-1", amount=100_000)


async def test_confirm_4xx_response_raises_payment_failed_error() -> None:
    """4xx 응답 시 PaymentFailedError가 발생한다."""
    gateway = _make_gateway()
    mock_resp = _mock_4xx_response(400)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.toss_secret_key = "test_secret"
        with pytest.raises(PaymentFailedError):
            await gateway.confirm(
                payment_key="k", order_id="RK-1", amount=100_000
            )


async def test_confirm_5xx_response_raises_payment_failed_error() -> None:
    """5xx 응답 시 PaymentFailedError가 발생한다."""
    gateway = _make_gateway()
    mock_resp = _mock_4xx_response(500)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.toss_secret_key = "test_secret"
        with pytest.raises(PaymentFailedError):
            await gateway.confirm(
                payment_key="k", order_id="RK-1", amount=100_000
            )


async def test_confirm_network_timeout_raises_gateway_unknown_error() -> None:
    """네트워크 타임아웃 시 PaymentGatewayUnknownError가 발생한다 (PaymentFailedError 아님)."""
    gateway = _make_gateway()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.toss_secret_key = "test_secret"
        with pytest.raises(PaymentGatewayUnknownError):
            await gateway.confirm(
                payment_key="k", order_id="RK-1", amount=100_000
            )


async def test_confirm_connect_error_raises_gateway_unknown_error() -> None:
    """커넥션 에러 시 PaymentGatewayUnknownError가 발생한다."""
    gateway = _make_gateway()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connect failed"))

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.toss_secret_key = "test_secret"
        with pytest.raises(PaymentGatewayUnknownError):
            await gateway.confirm(
                payment_key="k", order_id="RK-1", amount=100_000
            )


# ── get_payment (웹훅 수신 후 상태 재확인) ─────────────────────────


def _mock_get_payment_response(status: str = "DONE") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "paymentKey": "toss_key_abc",
        "status": status,
        "method": "카드",
        "totalAmount": 300_000,
        "balanceAmount": 0,
        "approvedAt": "2026-07-06T12:00:00+09:00",
        "card": {
            "issuerCode": "신한카드",
            "number": "1234567890001234",
            "installmentPlanMonths": 0,
            "approveNo": "12345678",
        },
    }
    return resp


def _client_with_get(get_result: object) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    if isinstance(get_result, BaseException):
        mock_client.get = AsyncMock(side_effect=get_result)
    else:
        mock_client.get = AsyncMock(return_value=get_result)
    return mock_client


async def test_get_payment_parses_status_and_metadata() -> None:
    """조회 응답의 status/카드 정보를 TossPaymentResult 로 파싱한다."""
    gateway = _make_gateway()
    mock_client = _client_with_get(_mock_get_payment_response("CANCELED"))

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.toss_secret_key = "test_secret"
        result = await gateway.get_payment(payment_key="toss_key_abc")

    assert result.status == "CANCELED"
    assert result.pg_tid == "toss_key_abc"
    assert result.total_amount == 300_000
    assert result.card_company == "신한카드"
    assert result.card_last4 == "1234"


async def test_get_payment_non_200_raises_gateway_unknown_error() -> None:
    """조회가 4xx/5xx 면 상태 불명 — PaymentGatewayUnknownError (웹훅 재시도 유도)."""
    gateway = _make_gateway()
    bad = MagicMock()
    bad.status_code = 404
    mock_client = _client_with_get(bad)

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.toss_secret_key = "test_secret"
        with pytest.raises(PaymentGatewayUnknownError):
            await gateway.get_payment(payment_key="toss_key_abc")


async def test_get_payment_network_error_raises_gateway_unknown_error() -> None:
    """조회 중 네트워크 에러 시 PaymentGatewayUnknownError."""
    gateway = _make_gateway()
    mock_client = _client_with_get(httpx.ConnectError("connect failed"))

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.toss_secret_key = "test_secret"
        with pytest.raises(PaymentGatewayUnknownError):
            await gateway.get_payment(payment_key="toss_key_abc")


# ── cancel (결제 취소/환불) ──────────────────────────────────────


def _client_with_post(post_result: object) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    if isinstance(post_result, BaseException):
        mock_client.post = AsyncMock(side_effect=post_result)
    else:
        mock_client.post = AsyncMock(return_value=post_result)
    return mock_client


def _mock_cancel_response(status: str = "CANCELED", balance: int = 0) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "paymentKey": "toss_key_abc",
        "status": status,
        "balanceAmount": balance,
        "cancels": [{"cancelAmount": 300_000, "transactionKey": "txn_1"}],
    }
    return resp


async def test_cancel_full_calls_api_with_reason() -> None:
    """전액 취소 — cancelReason 만 담고 cancelAmount 는 생략한다."""
    gateway = _make_gateway()
    mock_client = _client_with_post(_mock_cancel_response("CANCELED"))

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.toss_secret_key = "test_secret"
        result = await gateway.cancel(payment_key="toss_key_abc", reason="구매자 취소")

    url, kwargs = mock_client.post.call_args
    assert url[0].endswith("/toss_key_abc/cancel")
    assert kwargs["json"] == {"cancelReason": "구매자 취소"}
    assert result.status == "CANCELED"
    assert result.balance_amount == 0
    assert result.transaction_key == "txn_1"


async def test_cancel_partial_passes_cancel_amount() -> None:
    """부분 취소 — cancelAmount 를 body 에 담는다."""
    gateway = _make_gateway()
    mock_client = _client_with_post(
        _mock_cancel_response("PARTIAL_CANCELED", balance=100_000)
    )

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.toss_secret_key = "test_secret"
        result = await gateway.cancel(
            payment_key="toss_key_abc", reason="부분 환불", cancel_amount=200_000
        )

    _, kwargs = mock_client.post.call_args
    assert kwargs["json"]["cancelAmount"] == 200_000
    assert result.status == "PARTIAL_CANCELED"
    assert result.balance_amount == 100_000


async def test_cancel_sends_idempotency_key_header() -> None:
    """재시도 시 이중 취소를 막는 Idempotency-Key 헤더를 보낸다."""
    gateway = _make_gateway()
    mock_client = _client_with_post(_mock_cancel_response())

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.toss_secret_key = "test_secret"
        await gateway.cancel(payment_key="toss_key_abc", reason="취소")

    _, kwargs = mock_client.post.call_args
    assert "Idempotency-Key" in kwargs["headers"]
    assert "toss_key_abc" in kwargs["headers"]["Idempotency-Key"]


async def test_cancel_4xx_raises_payment_failed_with_toss_message() -> None:
    """취소 거절(4xx) 시 토스 {code, message} 를 담아 PaymentFailedError."""
    gateway = _make_gateway()
    bad = MagicMock()
    bad.status_code = 400
    bad.json.return_value = {
        "code": "ALREADY_CANCELED_PAYMENT",
        "message": "이미 취소된 결제 입니다.",
    }
    mock_client = _client_with_post(bad)

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.toss_secret_key = "test_secret"
        with pytest.raises(PaymentFailedError, match="ALREADY_CANCELED_PAYMENT"):
            await gateway.cancel(payment_key="toss_key_abc", reason="취소")


async def test_cancel_network_error_raises_gateway_unknown_error() -> None:
    """취소 중 네트워크 에러 — 성공 여부 불명이므로 PaymentGatewayUnknownError."""
    gateway = _make_gateway()
    mock_client = _client_with_post(httpx.ConnectError("connect failed"))

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.toss_secret_key = "test_secret"
        with pytest.raises(PaymentGatewayUnknownError):
            await gateway.cancel(payment_key="toss_key_abc", reason="취소")
