"""서비스·어댑터 로그 이벤트 검증 (관측성 O1-6 구조화 전환 / O1-7 로그 보강).

로그는 장애 분석·감사의 근거라 "무엇을 어떤 키로 남기는지" 를 고정한다.
event 는 값이 섞이지 않은 고정 문구, 값은 키워드 인자 — 검색과 마스킹이 키 기준이라서.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from structlog.testing import capture_logs

from app.auth.adapters.octomo import OctomoPhoneVerifier
from app.core.exceptions import (
    InvalidCredentialsError,
    PaymentFailedError,
    PaymentGatewayUnknownError,
)
from app.order.abandoned_order_sweeper import run_periodically
from app.order.admin_order_schemas import AdminOrderCancelRequest, AdminOrderStatusUpdate
from app.order.models import OrderStatus
from app.order.order_schemas import CreateOrderRequest, OrderItemRequest
from app.order.shipment import ShipmentMethod
from app.payment.models import PaymentStatus
from app.payment.payment_schemas import TossWebhookPayload
from app.payment.payment_service import PaymentService
from tests.test_admin_order_service import _make_order as _make_admin_order
from tests.test_admin_order_service import _make_service as _make_admin_service
from tests.test_auth_service import _FakeAuthRepo
from tests.test_auth_service import _make_service as _make_auth_service
from tests.test_auth_service import _make_user as _make_auth_user
from tests.test_octomo_adapter import _FakeRedis, _mock_client
from tests.test_order_service import _make_service as _make_order_service
from tests.test_order_service import make_address, make_order, make_product
from tests.test_payment_service import (
    _FakeEmailSender,
    _FakeGateway,
    _FakePaymentRepo,
    make_payment,
)
from tests.test_payment_service import make_order as make_payment_order
from tests.test_toss_adapter import _mock_4xx_response
from tests.test_user_service import _make_service as _make_user_service
from tests.test_user_service import _make_user as _make_plain_user


def _events(logs: list[dict[str, Any]], event: str) -> list[dict[str, Any]]:
    return [entry for entry in logs if entry["event"] == event]


# ── 인증 ──────────────────────────────────────────────────────


async def test_sign_in_unknown_login_id_logs_failure_without_raw_input() -> None:
    """없는 아이디 실패는 입력 원문을 남기지 않는다 — 아이디 칸에 비밀번호를 친 경우 유출 방지."""
    service = _make_auth_service(_FakeAuthRepo())

    with capture_logs() as logs, pytest.raises(InvalidCredentialsError):
        await service.sign_in(login_id="maybe-a-password", password="any")

    [entry] = _events(logs, "로그인 실패")
    assert entry["reason"] == "unknown_login_id"
    assert "maybe-a-password" not in str(entry)
    assert entry["log_level"] == "warning"


async def test_sign_in_wrong_password_logs_failure_with_user_id() -> None:
    """비밀번호 불일치는 user_id 로 남긴다 — 계정 단위 브루트포스 탐지용."""
    user = _make_auth_user(password="correct-pw")
    service = _make_auth_service(_FakeAuthRepo(user=user))

    with capture_logs() as logs, pytest.raises(InvalidCredentialsError):
        await service.sign_in(login_id=user.login_id, password="wrong-pw")

    [entry] = _events(logs, "로그인 실패")
    assert entry["reason"] == "wrong_password"
    assert entry["user_id"] == user.id


async def test_sign_in_inactive_user_logs_failure_reason() -> None:
    user = _make_auth_user(is_active=False)
    service = _make_auth_service(_FakeAuthRepo(user=user))

    with capture_logs() as logs, pytest.raises(InvalidCredentialsError):
        await service.sign_in(login_id=user.login_id, password="correct-pw")

    [entry] = _events(logs, "로그인 실패")
    assert entry["reason"] == "inactive"


async def test_sign_in_success_logs_user_id() -> None:
    user = _make_auth_user(password="correct-pw")
    service = _make_auth_service(_FakeAuthRepo(user=user))

    with capture_logs() as logs:
        await service.sign_in(login_id=user.login_id, password="correct-pw")

    [entry] = _events(logs, "로그인 성공")
    assert entry["user_id"] == user.id
    assert entry["log_level"] == "info"


# ── 회원 ──────────────────────────────────────────────────────


def test_change_password_failure_does_not_log_success() -> None:
    user = _make_plain_user(plain_password="actualpw1")
    service, _ = _make_user_service()

    with capture_logs() as logs, pytest.raises(InvalidCredentialsError):
        service.change_password(user=user, current_password="wrongpw1", new_password="new99zzz")

    assert _events(logs, "비밀번호 변경") == []


def test_change_password_logs_user_id() -> None:
    user = _make_plain_user(plain_password="old12345", must_change=True)
    service, _ = _make_user_service()

    with capture_logs() as logs:
        service.change_password(user=user, current_password="old12345", new_password="new99zzz")

    [entry] = _events(logs, "비밀번호 변경")
    assert entry["user_id"] == user.id
    assert entry["was_temp_password"] is True


async def test_withdraw_logs_user_id() -> None:
    user = _make_plain_user(plain_password="abc12345")
    service, _ = _make_user_service()

    with capture_logs() as logs:
        await service.withdraw(user=user, password="abc12345")

    [entry] = _events(logs, "회원 탈퇴")
    assert entry["user_id"] == user.id


# ── 주문 ──────────────────────────────────────────────────────


async def test_create_order_logs_order_number_and_amount() -> None:
    service = _make_order_service(
        products=[make_product(price=300_000, stock=5)], addresses=[make_address()]
    )
    req = CreateOrderRequest(
        items=[OrderItemRequest(product_id=1, quantity=2)],
        address_id=1,
        shipping_method=ShipmentMethod.PARCEL,
    )

    with capture_logs() as logs:
        result = await service.create_order(user_id=1, req=req, identity_verified=True)

    [entry] = _events(logs, "주문 생성")
    assert entry["order_number"] == result.order_number
    assert entry["user_id"] == 1
    assert entry["total_amount"] == result.total_amount
    assert entry["item_count"] == 1


async def test_cancel_order_logs_previous_status() -> None:
    order = make_order(status=OrderStatus.PAID)
    service = _make_order_service(orders=[order])

    with capture_logs() as logs:
        await service.cancel_order(user_id=1, order_number=order.order_number)

    [entry] = _events(logs, "주문 취소")
    assert entry["order_number"] == order.order_number
    assert entry["previous_status"] == "PAID"


async def test_request_refund_logs_order_number() -> None:
    order = make_order(order_id=1, user_id=1, status=OrderStatus.DELIVERED)
    service = _make_order_service(orders=[order])

    with capture_logs() as logs:
        await service.request_refund(user_id=1, order_number=order.order_number)

    [entry] = _events(logs, "환불 요청")
    assert entry["order_number"] == order.order_number


# ── 관리자 ────────────────────────────────────────────────────


async def test_admin_update_status_logs_transition() -> None:
    order = _make_admin_order()
    order.status = OrderStatus.PAID
    service = _make_admin_service(order)

    with capture_logs() as logs:
        await service.update_status(
            order.order_number, AdminOrderStatusUpdate(status=OrderStatus.PREPARING)
        )

    [entry] = _events(logs, "관리자 주문 상태 변경")
    assert entry["from_status"] == "PAID"
    assert entry["to_status"] == "PREPARING"


async def test_admin_cancel_order_logs_reason() -> None:
    order = _make_admin_order()
    order.status = OrderStatus.PAID
    service = _make_admin_service(order)

    with capture_logs() as logs:
        await service.cancel_order(order.order_number, AdminOrderCancelRequest(reason="재고 착오"))

    [entry] = _events(logs, "관리자 주문 취소")
    assert entry["order_number"] == order.order_number
    assert entry["previous_status"] == "PAID"
    assert entry["reason"] == "재고 착오"


async def test_admin_input_shipment_logs_carrier() -> None:
    from app.order.admin_order_schemas import AdminShipmentInput
    from app.order.admin_order_service import AdminOrderService
    from tests.test_admin_order_service import _FakeAdminOrderRepo

    class _RepoWithShipment(_FakeAdminOrderRepo):
        async def create_or_update_shipment(self, *_: object) -> None:
            return None

    order = _make_admin_order()
    order.status = OrderStatus.PAID
    service = AdminOrderService(_RepoWithShipment(order))  # type: ignore[arg-type]

    with capture_logs() as logs:
        await service.input_shipment(
            order.order_number, AdminShipmentInput(carrier="CJ대한통운", tracking_number="1234")
        )

    [entry] = _events(logs, "관리자 송장 입력")
    assert entry["from_status"] == "PAID"
    assert entry["carrier"] == "CJ대한통운"


# ── 결제 ──────────────────────────────────────────────────────


async def test_webhook_logs_received_with_structured_fields() -> None:
    """수동 테스트 체크리스트가 찾는 "토스 웹훅 수신" 로그 — 값은 키로 분리."""
    order = make_payment_order(order_id=1, status=OrderStatus.PENDING)
    payment = make_payment(order_id=1, status=PaymentStatus.READY, pg_tid="pk_done")
    repo = _FakePaymentRepo(orders=[order], payments=[payment])
    service = PaymentService(repo, _FakeGateway(), _FakeEmailSender())  # type: ignore[arg-type]

    with capture_logs() as logs:
        await service.handle_webhook(
            TossWebhookPayload(
                eventType="PAYMENT_STATUS_CHANGED",
                data={"paymentKey": "pk_done", "status": "DONE"},
            )
        )

    [entry] = _events(logs, "토스 웹훅 수신")
    assert entry["event_type"] == "PAYMENT_STATUS_CHANGED"
    assert entry["payment_key"] == "pk_done"
    assert entry["remote_status"] == "DONE"


async def test_toss_error_response_is_logged_with_status_code() -> None:
    from app.payment.adapters.toss import TossPaymentGateway

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=_mock_4xx_response(400))

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
        capture_logs() as logs,
        pytest.raises(PaymentFailedError),
    ):
        mock_settings.toss_secret_key = "test_secret"
        await TossPaymentGateway().confirm(payment_key="k", order_id="RK-1", amount=100_000)

    [entry] = _events(logs, "토스 API 오류 응답")
    assert entry["operation"] == "confirm"
    assert entry["status_code"] == 400


async def test_toss_transport_error_is_logged() -> None:
    from app.payment.adapters.toss import TossPaymentGateway

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(side_effect=httpx.ConnectTimeout("timeout"))

    with (
        patch("app.payment.adapters.toss.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=client),
        capture_logs() as logs,
        pytest.raises(PaymentGatewayUnknownError),
    ):
        mock_settings.toss_secret_key = "test_secret"
        await TossPaymentGateway().confirm(payment_key="k", order_id="RK-1", amount=100_000)

    [entry] = _events(logs, "토스 API 통신 실패")
    assert entry["operation"] == "confirm"
    assert entry["error"] == "ConnectTimeout"


# ── 외부 연동: Octomo ─────────────────────────────────────────


async def test_octomo_error_response_is_logged() -> None:
    verifier = OctomoPhoneVerifier(_FakeRedis())  # type: ignore[arg-type]
    resp = MagicMock()
    resp.status_code = 400
    resp.text = "bad request"

    with (
        patch("app.auth.adapters.octomo.settings") as mock_settings,
        patch("httpx.AsyncClient", return_value=_mock_client(resp)),
        capture_logs() as logs,
        pytest.raises(RuntimeError),
    ):
        mock_settings.octomo_api_key = "test_key"
        await verifier.issue_challenge("01012345678")

    [entry] = _events(logs, "Octomo API 오류 응답")
    assert entry["operation"] == "issue_challenge"
    assert entry["status_code"] == 400


# ── 스위퍼 ────────────────────────────────────────────────────


async def test_sweeper_logs_released_count() -> None:
    import asyncio

    calls = 0

    async def _sweep() -> int:
        nonlocal calls
        calls += 1
        return 2 if calls == 1 else 0

    with capture_logs() as logs:
        task = asyncio.create_task(run_periodically(_sweep, interval_seconds=0.01))
        for _ in range(100):
            if calls >= 2:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    [entry] = _events(logs, "방치 주문 정리")
    assert entry["released"] == 2


# ── 외부 연동: SMTP ───────────────────────────────────────────


async def test_gmail_send_failure_is_logged_and_reraised() -> None:
    """SMTP 실패는 수신자·에러 종류를 남기고 그대로 전파한다.

    호출부(BG task)의 재시도/무시 판단은 그대로 유지.
    """
    from app.common.email.gmail_adapter import GmailSmtpEmailSender

    sender = GmailSmtpEmailSender(user="noreply@example.com", password="app-pw")

    with (
        patch("aiosmtplib.send", AsyncMock(side_effect=OSError("connection refused"))),
        capture_logs() as logs,
        pytest.raises(OSError),
    ):
        await sender.send(to="hong@example.com", subject="인증코드", body="123456")

    [entry] = _events(logs, "메일 발송 실패")
    assert entry["to_email"] == "hong@example.com"  # 마스킹은 출력 단계(processor)에서
    assert entry["error"] == "OSError"
    assert entry["subject"] == "인증코드"
