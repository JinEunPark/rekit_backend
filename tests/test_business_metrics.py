"""비즈니스 메트릭 — 결제·주문·가입·방치 주문 정리·PG 지연이 Prometheus 에 기록되는지.

각 도메인 테스트의 fake 를 재사용한다. 메트릭은 프로세스 전역이라 전후 차이로 검증.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks
from prometheus_client import REGISTRY

from app.core.exceptions import PaymentFailedError, PaymentGatewayUnknownError
from app.core.security import create_social_signup_token
from app.order.abandoned_order_sweeper import run_periodically
from app.order.order_schemas import CreateOrderRequest, OrderItemRequest
from app.order.shipment import ShipmentMethod
from app.payment.adapters.toss import TossPaymentGateway
from app.payment.payment_schemas import PaymentConfirmRequest, TossWebhookPayload
from tests.test_auth_service import _FakeAuthRepo, _sign_up_req
from tests.test_auth_service import _make_service as _make_auth_service
from tests.test_order_service import _make_service as _make_order_service
from tests.test_order_service import make_address, make_product
from tests.test_payment_service import _FakeGateway, make_order, make_payment
from tests.test_payment_service import _make_service as _make_payment_service
from tests.test_social_login import _FakeAuthRepo as _FakeSocialRepo
from tests.test_social_login import _make_service as _make_social_service
from tests.test_toss_adapter import _mock_200_response


def _sample(name: str, labels: dict[str, str] | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


def _confirm_req() -> PaymentConfirmRequest:
    return PaymentConfirmRequest(payment_key="k", order_id="RK-2606200001", amount=300_000)


# ── 결제 승인 결과 ───────────────────────────────────────────────


async def test_confirm_rejected_by_pg_counts_failed() -> None:
    """토스가 승인을 거절하면 result=failed."""
    service = _make_payment_service(
        orders=[make_order()],
        payments=[make_payment(order_id=1)],
        gateway=_FakeGateway(should_fail=True),
    )
    before = _sample("rekle_payment_confirm_total", {"result": "failed"})

    with pytest.raises(PaymentFailedError):
        await service.confirm_payment(_confirm_req(), BackgroundTasks())

    assert _sample("rekle_payment_confirm_total", {"result": "failed"}) == before + 1


async def test_confirm_pg_timeout_counts_unknown() -> None:
    """응답을 못 받아 결과를 모르면 result=unknown — 사람이 봐야 하는 신호라 failed 와 분리."""
    service = _make_payment_service(
        orders=[make_order()],
        payments=[make_payment(order_id=1)],
        gateway=_FakeGateway(should_timeout=True),
    )
    before = _sample("rekle_payment_confirm_total", {"result": "unknown"})

    with pytest.raises(PaymentGatewayUnknownError):
        await service.confirm_payment(_confirm_req(), BackgroundTasks())

    assert _sample("rekle_payment_confirm_total", {"result": "unknown"}) == before + 1


async def test_confirm_validation_failure_before_pg_is_not_counted() -> None:
    """금액 불일치처럼 PG 호출 전에 거절된 건 PG 승인 결과로 세지 않는다."""
    service = _make_payment_service(orders=[make_order()], payments=[make_payment(order_id=1)])
    before = sum(
        _sample("rekle_payment_confirm_total", {"result": r})
        for r in ("success", "failed", "unknown")
    )

    with pytest.raises(PaymentFailedError):
        await service.confirm_payment(
            PaymentConfirmRequest(payment_key="k", order_id="RK-2606200001", amount=999_999),
            BackgroundTasks(),
        )

    after = sum(
        _sample("rekle_payment_confirm_total", {"result": r})
        for r in ("success", "failed", "unknown")
    )
    assert after == before


async def test_confirm_success_counts_success() -> None:
    """승인 성공 시 result=success."""
    service = _make_payment_service(orders=[make_order()], payments=[make_payment(order_id=1)])
    before = _sample("rekle_payment_confirm_total", {"result": "success"})

    await service.confirm_payment(_confirm_req(), BackgroundTasks())

    assert _sample("rekle_payment_confirm_total", {"result": "success"}) == before + 1


async def test_webhook_counts_by_refetched_remote_status() -> None:
    """웹훅은 body 가 아닌 조회 API 로 재확인한 실제 상태로 센다."""
    service = _make_payment_service(
        orders=[make_order()],
        payments=[make_payment(order_id=1, pg_tid="pk_metric")],
        gateway=_FakeGateway(payment_status="ABORTED"),
    )
    before = _sample("rekle_payment_webhook_received_total", {"remote_status": "ABORTED"})

    await service.handle_webhook(
        TossWebhookPayload(
            eventType="PAYMENT_STATUS_CHANGED", data={"paymentKey": "pk_metric", "status": "DONE"}
        )
    )

    assert (
        _sample("rekle_payment_webhook_received_total", {"remote_status": "ABORTED"}) == before + 1
    )


# ── 토스 API 지연 ────────────────────────────────────────────────


async def test_toss_confirm_call_observes_pg_latency() -> None:
    """토스 confirm 호출 시간이 operation=confirm Histogram 에 관측된다."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_200_response())
    labels = {"operation": "confirm"}
    before = _sample("rekle_pg_request_duration_seconds_count", labels)

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.toss_secret_key = "test_secret"
        await TossPaymentGateway().confirm(
            payment_key="k", order_id="RK-2606200001", amount=300_000
        )

    assert _sample("rekle_pg_request_duration_seconds_count", labels) == before + 1


# ── 주문·가입·방치 주문 ──────────────────────────────────────────


async def test_create_order_counts_created_order() -> None:
    """주문 생성이 끝나면 생성 주문 수가 1 증가한다."""
    service = _make_order_service(
        products=[make_product(price=300_000, stock=5)], addresses=[make_address()]
    )
    req = CreateOrderRequest(
        items=[OrderItemRequest(product_id=1, quantity=1)],
        address_id=1,
        shipping_method=ShipmentMethod.PARCEL,
    )
    before = _sample("rekle_orders_created_total")

    await service.create_order(user_id=1, req=req, identity_verified=True)

    assert _sample("rekle_orders_created_total") == before + 1


async def test_email_sign_up_counts_signup_with_email_provider() -> None:
    """아이디·비밀번호 가입은 provider=email."""
    service = _make_auth_service(_FakeAuthRepo())
    before = _sample("rekle_signups_total", {"provider": "email"})

    await service.sign_up(_sign_up_req())

    assert _sample("rekle_signups_total", {"provider": "email"}) == before + 1


async def test_social_sign_up_counts_signup_with_social_provider() -> None:
    """소셜 가입은 provider=kakao|naver|google."""
    service = _make_social_service(_FakeSocialRepo())
    temp = create_social_signup_token(
        provider="kakao", social_id="kakao-metric", email="metric@example.com", name="메트릭"
    )
    before = _sample("rekle_signups_total", {"provider": "kakao"})

    await service.social_sign_up(temp_token=temp, agreed_marketing=False)

    assert _sample("rekle_signups_total", {"provider": "kakao"}) == before + 1


async def test_sweeper_counts_released_orders() -> None:
    """스위퍼가 정리한 방치 주문 건수만큼 증가한다."""
    before = _sample("rekle_abandoned_orders_released_total")
    calls = 0

    async def _sweep() -> int:
        nonlocal calls
        calls += 1
        return 3 if calls == 1 else 0

    task = asyncio.create_task(run_periodically(_sweep, interval_seconds=0.01))
    for _ in range(100):
        if calls >= 2:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert _sample("rekle_abandoned_orders_released_total") == before + 3
