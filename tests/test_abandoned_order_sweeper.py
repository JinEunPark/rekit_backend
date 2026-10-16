"""방치 주문 스위퍼 주기 실행 루프 단위 테스트."""

from __future__ import annotations

import asyncio

import pytest

from app.order.abandoned_order_sweeper import run_periodically


async def test_run_periodically_keeps_running_after_sweep_error() -> None:
    """한 번 실패해도 루프가 죽지 않고 다음 주기에 다시 실행된다."""
    calls = 0

    async def _sweep() -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("DB 일시 장애")
        return 0

    task = asyncio.create_task(run_periodically(_sweep, interval_seconds=0.01))
    for _ in range(100):
        if calls >= 3:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls >= 3
