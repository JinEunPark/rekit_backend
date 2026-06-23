from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.catalog.models import ConditionGrade


class FavoriteProductItem(BaseModel):
    """관심상품 목록 카드용."""

    model_config = ConfigDict(from_attributes=True)

    product_id: int
    title: str
    price: int
    original_price: int | None
    discount_pct: int | None
    thumbnail_url: str | None
    category: str
    condition_grade: ConditionGrade
    warranty_works: bool
    added_at: datetime


class FavoriteToggleResponse(BaseModel):
    """POST/DELETE /favorites/{product_id} 공통 응답."""

    product_id: int
    is_favorite: bool
