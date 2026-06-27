"""catalog 모듈 Pydantic 스키마.

- ProductSort: 목록 정렬 옵션
- ProductListParams: GET /products 쿼리 파라미터 묶음 (Depends() 로 주입)
- ProductResponse: 목록 카드용 (thumbnail_url + discount_pct 계산값 포함)
- ProductDetailResponse: 상세 (이미지 목록 포함)
- CategoryMetaItem: GET /categories 응답 (DB 기반 동적)
"""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field

from app.catalog.models import ConditionGrade, ProductStatus
from app.core.pagination import PageMeta


class ProductSort(str, enum.Enum):
    LATEST = "latest"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"


class BulkProductRequest(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=100)


class ProductListParams(BaseModel):
    """GET /products 쿼리 파라미터. FastAPI Depends() 로 자동 주입."""

    category: str | None = None
    grade: ConditionGrade | None = None
    min_price: int | None = Field(default=None, ge=0)
    max_price: int | None = Field(default=None, ge=0)
    warranty: bool | None = None
    q: str | None = None
    sort: ProductSort = ProductSort.LATEST
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


# ── 응답 스키마 ─────────────────────────────────────────────


class ProductImageResponse(BaseModel):
    id: int
    url: str
    sort_order: int
    label: str | None


class ProductResponse(BaseModel):
    """목록 카드용. discount_pct / thumbnail_url 은 service 레이어에서 계산."""

    id: int
    title: str
    category: str
    brand: str | None
    condition_grade: ConditionGrade
    warranty_works: bool
    price: int
    original_price: int | None
    discount_pct: int | None  # 0-100, original_price 없으면 None
    status: ProductStatus
    thumbnail_url: str | None  # images[0].url, 이미지 없으면 None
    created_at: datetime


class ProductDetailResponse(ProductResponse):
    """상세 페이지용. ProductResponse + 설명·스펙·이미지 목록."""

    description: str
    model_name: str | None
    year_estimate: int | None
    weight_kg: float | None
    width_cm: int | None
    depth_cm: int | None
    height_cm: int | None
    stock: int
    images: list[ProductImageResponse]


class ProductListResponse(BaseModel):
    items: list[ProductResponse]
    meta: PageMeta


# ── 카테고리 응답 스키마 ────────────────────────────────────


class CategoryMetaItem(BaseModel):
    id: str
    label: str
    icon: str
    sort_order: int
