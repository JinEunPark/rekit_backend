"""이벤트 루프 지연 측정 (todo O2-8).

`asyncio.sleep(interval)` 이 예정보다 늦게 깨어난 만큼 = 그동안 루프가 막힌 시간.
bcrypt 같은 동기 호출이 워커의 모든 요청을 멈추는지(O8-1) 직접 수치로 본다.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from prometheus_client import REGISTRY

from app.core.event_loop_lag import measure_event_loop_lag, run_event_loop_lag_monitor
from app.main import _start_event_loop_lag_monitor


def _lag_count() -> float:
    return REGISTRY.get_sample_value("rekle_event_loop_lag_seconds_count") or 0.0


async def test_measure_event_loop_lag_observes_blocking_call() -> None:
    """측정 중 다른 코루틴이 루프를 동기로 막으면, 막은 시간만큼 지연이 관측된다."""
    before = _lag_count()
    task = asyncio.create_task(measure_event_loop_lag(0.01))
    await asyncio.sleep(0)  # 측정 태스크가 먼저 sleep 에 들어가게

    time.sleep(0.1)  # 루프 블로킹 (bcrypt 등 동기 호출 대역)
    lag = await task

    assert lag >= 0.08
    assert _lag_count() == before + 1


async def test_measure_event_loop_lag_is_near_zero_on_idle_loop() -> None:
    """막는 코드가 없으면 지연은 거의 0 이다 (음수로 기록하지 않는다)."""
    lag = await measure_event_loop_lag(0.01)

    assert 0.0 <= lag < 0.05


async def test_run_event_loop_lag_monitor_keeps_measuring_until_cancelled() -> None:
    """백그라운드 루프는 주기마다 측정을 계속하고, cancel 하면 깨끗이 끝난다 (lifespan 종료)."""
    before = _lag_count()
    task = asyncio.create_task(run_event_loop_lag_monitor(interval_seconds=0.01))

    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert _lag_count() >= before + 2


def test_start_event_loop_lag_monitor_disabled_when_interval_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """주기 0 이면 측정 태스크를 띄우지 않는다 (스위퍼와 같은 규약)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "event_loop_lag_interval_seconds", 0)

    assert _start_event_loop_lag_monitor() is None
