"""방치된 PENDING 주문 주기 정리 (스위퍼).

결제창을 닫거나 탭을 닫고 떠난 주문은 다시 열어보는 사람이 없으면 재고를 계속 잡고 있다.
결제 기한이 지난 PENDING 주문을 주기적으로 찾아 `PaymentService.release_pending_order` 로
안전하게 정리한다 (결제창을 연 주문은 토스 실상태를 확인한 뒤에만 취소).

- 주문 1건 = 트랜잭션 1개. 토스 조회가 느리거나 한 건이 실패해도 다른 건에 영향 없음
- `FOR UPDATE SKIP LOCKED` 로 한 건씩 가져가므로 gunicorn 워커마다 돌아도 같은 주문을
  두 번 처리하지 않는다 (별도 분산 락 불필요)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.email import EmailSender
from app.order.order_repository import OrderRepository
from app.order.order_service import PAYMENT_TIMEOUT
from app.payment.adapters.ports import PaymentGateway
from app.payment.payment_repository import PaymentRepository
from app.payment.payment_service import PaymentService

logger = logging.getLogger(__name__)


async def sweep_abandoned_orders(
    session_factory: async_sessionmaker[AsyncSession],
    gateway: PaymentGateway,
    email_sender: EmailSender,
    *,
    now: datetime | None = None,
    max_orders: int = 50,
) -> int:
    """결제 기한이 지난 PENDING 주문을 정리하고, 실제로 취소한 건수를 반환한다.

    정리를 보류한 주문(토스 조회 실패 등)은 이번 스윕에서 제외하고 다음 주기에 다시 본다.
    """
    cutoff = (now or datetime.now(UTC)) - PAYMENT_TIMEOUT
    skipped: list[int] = []
    released = 0
    for _ in range(max_orders):
        async with session_factory() as session:
            order_id = await OrderRepository(session).claim_stale_pending_order_id(
                cutoff, exclude=skipped
            )
            if order_id is None:
                break
            service = PaymentService(PaymentRepository(session), gateway, email_sender)
            if await service.release_pending_order(order_id):
                released += 1
            else:
                skipped.append(order_id)
            await session.commit()
    return released


async def run_periodically(
    sweep: Callable[[], Awaitable[int]], *, interval_seconds: float
) -> None:
    """lifespan 백그라운드 루프. 한 번 실패해도 죽지 않고 다음 주기에 다시 시도한다."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            released = await sweep()
        except Exception:
            logger.exception("방치 주문 스윕 실패 — 다음 주기에 재시도")
            continue
        if released:
            logger.info("방치 주문 %d건 정리 (재고 복구)", released)
