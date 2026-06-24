from math import ceil

from pydantic import BaseModel, Field


class PageParams(BaseModel):
    page: int = Field(default=1, ge=1, description="페이지 번호 (1부터 시작)")
    size: int = Field(default=10, ge=1, le=100, description="페이지 크기 (1-100)")

class CursorParams(BaseModel):         # ?cursor=abc&limit=20 (무한스크롤)
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=100)

class PageMeta(BaseModel):
    page: int
    size: int
    total: int
    total_pages: int


def page_meta(total: int, params: PageParams) -> PageMeta:
    return PageMeta(
        page=params.page,
        size=params.size,
        total=total,
        total_pages=ceil(total / params.size) if total else 0,
    )


def build_page_meta(total: int, page: int, size: int) -> PageMeta:
    """page/size 를 직접 받는 변형 — PageParams 를 상속하지 않는 쿼리 파라미터용."""
    return PageMeta(
        page=page,
        size=size,
        total=total,
        total_pages=ceil(total / size) if total else 0,
    )