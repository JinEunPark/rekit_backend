"""이벤트 루프 지연 측정 — lifespan 백그라운드 태스크 (todo O2-8).

asyncio 워커는 한 스레드에서 모든 요청을 돌리므로, 동기 블로킹 호출(bcrypt 등) 하나가 그 워커의
모든 요청을 멈춘다. 응답시간 p95 로는 원인이 섞여 보이지만, 정해진 시간만큼 sleep 한 뒤 실제로
늦게 깨어난 만큼을 재면 "루프가 막혔던 시간" 을 직접 볼 수 있다.
"""

from __future__ import annotations

import asyncio

from app.core.metrics import EVENT_LOOP_LAG_SECONDS


async def measure_event_loop_lag(interval_seconds: float) -> float:
    """interval 만큼 sleep 하고 예정보다 늦게 깨어난 시간(초)을 기록·반환한다."""
    loop = asyncio.get_running_loop()
    start = loop.time()
    await asyncio.sleep(interval_seconds)
    # 타이머 해상도 때문에 아주 약간 일찍 깨어날 수 있다 — 음수는 지연 없음으로 본다
    lag = max(0.0, loop.time() - start - interval_seconds)
    EVENT_LOOP_LAG_SECONDS.observe(lag)
    return lag


async def run_event_loop_lag_monitor(*, interval_seconds: float) -> None:
    """cancel 될 때까지 주기적으로 측정한다."""
    while True:
        await measure_event_loop_lag(interval_seconds)
