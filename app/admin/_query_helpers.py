"""admin 모듈 공용 쿼리 헬퍼."""

from __future__ import annotations

from typing import Literal

from sqlalchemy import ColumnElement, ColumnExpressionArgument, func, literal_column

TruncUnit = Literal["day", "week"]


def date_trunc_literal(
    unit: TruncUnit, column: ColumnExpressionArgument[object]
) -> ColumnElement[object]:
    """Postgres date_trunc 을 SELECT/GROUP BY/ORDER BY 가 공유할 단일 표현식으로 반환한다.

    `func.date_trunc(unit, column)` 을 절마다 따로 호출하면 `unit` 문자열이 매번
    별개의 bind parameter 로 바인딩되어 Postgres 가 세 절을 동일 표현식으로 인식하지
    못하고 "column must appear in GROUP BY" (GroupingError) 를 낸다. 호출자는 이
    함수가 반환한 같은 객체를 SELECT/GROUP BY/ORDER BY 모두에 재사용해야 한다.

    `unit` 을 `Literal["day", "week"]` 로 제한해 `literal_column` 인라인이 항상
    안전하도록 타입 레벨에서 강제한다 (임의 문자열이 SQL에 그대로 들어갈 수 없음).
    """
    return func.date_trunc(literal_column(f"'{unit}'"), column)
