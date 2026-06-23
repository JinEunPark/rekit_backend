"""관리자 상품·카테고리 CRUD Pydantic 스키마."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.catalog.models import ConditionGrade, ProductStatus
from app.core.pagination import PageMeta


class AdminProductCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="")
    category: str = Field(min_length=1, max_length=30)
    brand: str | None = None
    model_name: str | None = None
    year_estimate: int | None = None
    condition_grade: ConditionGrade
    warranty_works: bool = False
    price: int = Field(ge=0)
    original_price: int | None = None
    weight_kg: float | None = None
    width_cm: int | None = None
    depth_cm: int | None = None
    height_cm: int | None = None
    stock: int = Field(default=1, ge=0)
    status: ProductStatus = ProductStatus.ACTIVE
    image_urls: list[str] = Field(default_factory=list, max_length=10)


class AdminProductUpdate(BaseModel):
    """PATCH /admin/products/{id} — 보내지 않은 필드는 유지."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    category: str | None = Field(default=None, min_length=1, max_length=30)
    brand: str | None = None
    model_name: str | None = None
    year_estimate: int | None = None
    condition_grade: ConditionGrade | None = None
    warranty_works: bool | None = None
    price: int | None = Field(default=None, ge=0)
    original_price: int | None = None
    weight_kg: float | None = None
    width_cm: int | None = None
    depth_cm: int | None = None
    height_cm: int | None = None
    stock: int | None = Field(default=None, ge=0)
    status: ProductStatus | None = None


class AdminImageItem(BaseModel):
    """이미지 교체 요청의 개별 항목.

    sort_order 는 배열 인덱스에서 자동 부여 — 원하는 순서대로 나열하면 된다.
    """

    url: str = Field(min_length=1, max_length=500)
    label: str | None = None


class AdminProductImagesReplace(BaseModel):
    """PUT /admin/products/{id}/images 요청 본문.

    기존 이미지를 전부 지우고 여기 담긴 목록으로 원자적으로 교체한다.
    빈 리스트를 보내면 모든 이미지가 삭제된다.
    """

    images: list[AdminImageItem] = Field(default_factory=list, max_length=10)


class AdminProductListParams(BaseModel):
    status: ProductStatus | None = None
    q: str | None = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


class AdminProductImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    url: str
    sort_order: int
    label: str | None


class AdminProductDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: str
    category: str
    brand: str | None
    model_name: str | None
    year_estimate: int | None
    condition_grade: ConditionGrade
    warranty_works: bool
    price: int
    original_price: int | None
    discount_pct: int | None
    weight_kg: float | None
    width_cm: int | None
    depth_cm: int | None
    height_cm: int | None
    stock: int
    status: ProductStatus
    images: list[AdminProductImageResponse]
    created_at: datetime


class AdminProductListResponse(BaseModel):
    items: list[AdminProductDetailResponse]
    meta: PageMeta


# ── 카테고리 CRUD 스키마 ────────────────────────────────────


class AdminCategoryCreate(BaseModel):
    """POST /admin/categories — 카테고리 신규 등록."""

    id: str = Field(min_length=1, max_length=30, pattern=r"^[A-Z][A-Z0-9_]*$")
    title: str = Field(min_length=1, max_length=100)
    icon: str = Field(min_length=1, max_length=50)
    sort_order: int = Field(default=0, ge=0)


class AdminCategoryUpdate(BaseModel):
    """PATCH /admin/categories/{id} — 보내지 않은 필드는 유지."""

    title: str | None = Field(default=None, min_length=1, max_length=100)
    icon: str | None = Field(default=None, min_length=1, max_length=50)
    sort_order: int | None = Field(default=None, ge=0)


class AdminCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    icon: str
    sort_order: int
