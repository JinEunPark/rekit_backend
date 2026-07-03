"""cart 모듈 Service — 장바구니 비즈니스 로직."""

from __future__ import annotations

from app.cart.cart_repository import CartRepository
from app.cart.cart_schemas import (
    AddToCartRequest,
    CartItemProductSummary,
    CartItemResponse,
    CartResponse,
    CartSummary,
    UpdateCartItemRequest,
)
from app.cart.models import CartItem
from app.catalog.models import Product, ProductStatus
from app.core.exceptions import CartItemNotFoundError, OutOfStockError, ProductNotFoundError

# 화물택배 기준 안내값 — 실제 주문 생성 시 상품 치수/무게로 재계산
_SHIPPING_FEE_ESTIMATE = 60_000


class CartService:
    def __init__(self, repo: CartRepository) -> None:
        self._repo = repo

    # ── 내부 헬퍼 ───────────────────────────────────────────────

    def _build_item_response(self, item: CartItem) -> CartItemResponse:
        product = item.product
        thumbnail_url = product.images[0].url if product.images else None
        product_summary = CartItemProductSummary(
            id=product.id,
            title=product.title,
            price=product.price,
            thumbnail_url=thumbnail_url,
            status=product.status,
            stock=product.stock,
        )
        return CartItemResponse(
            id=item.id,
            product=product_summary,
            quantity=item.quantity,
            subtotal=product.price * item.quantity,
        )

    async def _build_cart_response(self, user_id: int) -> CartResponse:
        """user_id 의 전체 장바구니를 조회해 CartResponse 로 변환."""
        items = await self._repo.get_all_by_user_id(user_id)
        item_responses = [self._build_item_response(i) for i in items]
        items_total = sum(r.subtotal for r in item_responses)
        return CartResponse(
            items=item_responses,
            summary=CartSummary(
                items_total=items_total,
                shipping_fee_estimate=_SHIPPING_FEE_ESTIMATE,
                total=items_total + _SHIPPING_FEE_ESTIMATE,
            ),
        )

    # ── 공개 API ─────────────────────────────────────────────────

    async def get_cart(self, user_id: int) -> CartResponse:
        return await self._build_cart_response(user_id)

    async def add_item(self, user_id: int, data: AddToCartRequest) -> CartResponse:
        """상품을 장바구니에 추가. 이미 있으면 수량 합산(upsert).

        Raises:
            ProductNotFoundError (404): 상품이 존재하지 않거나 ACTIVE 상태가 아닐 때.
            OutOfStockError (422): 요청 수량이 재고를 초과할 때.
        """
        existing = await self._repo.get_by_user_and_product(user_id, data.product_id)

        if existing is not None:
            product: Product | None = existing.product
            if product is None or product.status != ProductStatus.ACTIVE:
                raise ProductNotFoundError()
            new_quantity = existing.quantity + data.quantity
            if new_quantity > product.stock:
                raise OutOfStockError()
            existing.quantity = new_quantity
            await self._repo.save(existing)
        else:
            product = await self._repo.get_product(data.product_id)
            if product is None or product.status != ProductStatus.ACTIVE:
                raise ProductNotFoundError()
            if data.quantity > product.stock:
                raise OutOfStockError()
            new_item = CartItem(
                user_id=user_id,
                product_id=data.product_id,
                quantity=data.quantity,
            )
            new_item.product = product
            await self._repo.save(new_item)

        return await self._build_cart_response(user_id)

    async def update_item(
        self, user_id: int, item_id: int, data: UpdateCartItemRequest
    ) -> CartResponse:
        """장바구니 항목 수량 수정.

        Raises:
            CartItemNotFoundError (404): 항목이 없거나 다른 사용자 소유일 때.
            OutOfStockError (422): 수정 수량이 재고를 초과할 때.
        """
        item = await self._repo.get_by_id(item_id)
        if item is None or item.user_id != user_id:
            raise CartItemNotFoundError()

        product = item.product
        if data.quantity > product.stock:
            raise OutOfStockError()

        item.quantity = data.quantity
        await self._repo.save(item)
        return await self._build_cart_response(user_id)

    async def remove_item(self, user_id: int, item_id: int) -> None:
        """장바구니 항목 단건 삭제.

        Raises:
            CartItemNotFoundError (404): 항목이 없거나 다른 사용자 소유일 때.
        """
        item = await self._repo.get_by_id(item_id)
        if item is None or item.user_id != user_id:
            raise CartItemNotFoundError()
        await self._repo.delete(item)

    async def bulk_remove(self, user_id: int, item_ids: list[int]) -> None:
        """장바구니 항목 일괄 삭제. user_id 조건으로 타인 항목 삭제 차단."""
        await self._repo.delete_by_ids(user_id, item_ids)
