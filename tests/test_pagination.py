"""PageParams / CursorParams / page_meta 단위 테스트.

라우터를 거치지 않고 Pydantic 모델만 검증한다 (FastAPI 422 응답은 결국
이 ValidationError 가 만드는 것이라 모델 단위에서 막히면 라우터에서도 막힌다).
"""

import pytest
from pydantic import ValidationError

from app.core.pagination import CursorParams, PageMeta, PageParams, page_meta

# ── PageParams: 기본값 / 정상 입력 ──────────────────────────


def test_page_params_defaults() -> None:
    p = PageParams()
    assert p.page == 1
    assert p.size == 10


def test_page_params_valid_values() -> None:
    p = PageParams(page=3, size=50)
    assert p.page == 3
    assert p.size == 50


# ── PageParams: 경계값 거부 ───────────────────────────────


def test_page_params_rejects_zero_page() -> None:
    with pytest.raises(ValidationError):
        PageParams(page=0)


def test_page_params_rejects_negative_page() -> None:
    with pytest.raises(ValidationError):
        PageParams(page=-1)


def test_page_params_rejects_size_zero() -> None:
    with pytest.raises(ValidationError):
        PageParams(size=0)


def test_page_params_rejects_size_over_max() -> None:
    with pytest.raises(ValidationError):
        PageParams(size=101)


def test_page_params_rejects_non_int_page() -> None:
    with pytest.raises(ValidationError):
        PageParams(page="abc")  # type: ignore[arg-type]


# ── CursorParams ─────────────────────────────────────────


def test_cursor_params_defaults() -> None:
    c = CursorParams()
    assert c.cursor is None
    assert c.limit == 20


def test_cursor_params_with_cursor() -> None:
    c = CursorParams(cursor="p_42", limit=30)
    assert c.cursor == "p_42"
    assert c.limit == 30


def test_cursor_params_rejects_limit_over_max() -> None:
    with pytest.raises(ValidationError):
        CursorParams(limit=101)


def test_cursor_params_rejects_limit_zero() -> None:
    with pytest.raises(ValidationError):
        CursorParams(limit=0)


# ── page_meta 헬퍼 ─────────────────────────────────────────


def test_page_meta_calculates_total_pages_exact_division() -> None:
    meta = page_meta(total=100, params=PageParams(page=1, size=20))
    assert isinstance(meta, PageMeta)
    assert meta.total == 100
    assert meta.total_pages == 5


def test_page_meta_rounds_up_partial_page() -> None:
    meta = page_meta(total=124, params=PageParams(page=1, size=20))
    assert meta.total_pages == 7  # ceil(124 / 20)


def test_page_meta_handles_zero_total() -> None:
    meta = page_meta(total=0, params=PageParams())
    assert meta.total_pages == 0


def test_page_meta_preserves_page_and_size() -> None:
    meta = page_meta(total=50, params=PageParams(page=3, size=20))
    assert meta.page == 3
    assert meta.size == 20
