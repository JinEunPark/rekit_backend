"""주문번호 생성 유틸리티.

포맷: RK-YYMMDD{id:04d}
예)  RK-2606200001  (2026-06-20, id=1)
"""

from __future__ import annotations

from datetime import UTC, datetime


def build_order_number(order_id: int, now: datetime | None = None) -> str:
    """RK-YYMMDD{id:04d} 포맷의 주문번호를 생성한다.

    Args:
        order_id: DB에서 flush 후 획득한 PK 정수값.
        now: 날짜 기준 시각. None 이면 datetime.now(UTC) 사용.
             테스트에서 고정 날짜를 주입할 때 사용.

    Returns:
        "RK-YYMMDD####" 형식 문자열 (예: "RK-2606200001").
    """
    ts = now if now is not None else datetime.now(UTC)
    date_part = ts.strftime("%y%m%d")
    return f"RK-{date_part}{order_id:04d}"
