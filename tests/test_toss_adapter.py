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
    """card 정보 없을 때 card_last4가 None으로 반환된다."""
    gateway = _make_gateway()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "method": "가상계좌",
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
