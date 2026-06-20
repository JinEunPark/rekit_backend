"""cart 모듈 Pydantic 스키마 (DTO).

api.md §4 장바구니 API 요청/응답 타입 정의.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.catalog.models import ProductStatus


class AddToCartRequest(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1, le=10)


class UpdateCartItemRequest(BaseModel):
    quantity: int = Field(ge=1, le=10)


class BulkDeleteRequest(BaseModel):
    item_ids: list[int]


class CartItemProductSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    price: int
    thumbnail_url: str | None  # 서비스에서 images[0].url 로 계산
    status: ProductStatus
    stock: int


class CartItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product: CartItemProductSummary
    quantity: int
    subtotal: int  # price * quantity, 서비스에서 계산


class CartSummary(BaseModel):
    items_total: int
    shipping_fee_estimate: int  # 화물택배 기준 안내값 — 실제 주문 시 재계산
    total: int


class CartResponse(BaseModel):
    items: list[CartItemResponse]
    summary: CartSummary
