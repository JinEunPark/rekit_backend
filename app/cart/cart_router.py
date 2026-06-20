"""cart 모듈 Router — /cart prefix.

api.md §4 장바구니 API:
- GET    /cart                     : 장바구니 조회
- POST   /cart/items               : 상품 담기 (201)
- PATCH  /cart/items/{item_id}     : 수량 수정
- DELETE /cart/items/{item_id}     : 단건 삭제 (204)
- POST   /cart/items/bulk-delete   : 일괄 삭제 (204)
"""

from fastapi import APIRouter, Depends, status

from app.cart.cart_schemas import (
    AddToCartRequest,
    BulkDeleteRequest,
    CartResponse,
    UpdateCartItemRequest,
)
from app.cart.cart_service import CartService
from app.core.deps import get_active_user, get_cart_service
from app.user.models import User

router = APIRouter(prefix="/cart", tags=["cart"])


@router.get(
    "",
    response_model=CartResponse,
    status_code=status.HTTP_200_OK,
    summary="장바구니 조회",
)
async def get_cart(
    user: User = Depends(get_active_user),
    service: CartService = Depends(get_cart_service),
) -> CartResponse:
    """로그인 사용자의 장바구니 전체 조회."""
    return await service.get_cart(user.id)


@router.post(
    "/items",
    response_model=CartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="장바구니 상품 담기",
)
async def add_item(
    body: AddToCartRequest,
    user: User = Depends(get_active_user),
    service: CartService = Depends(get_cart_service),
) -> CartResponse:
    """상품을 장바구니에 추가. 이미 담긴 상품이면 수량을 합산한다.

    Errors:
    - PRODUCT_NOT_FOUND (404): 상품이 존재하지 않거나 ACTIVE 상태가 아님
    - OUT_OF_STOCK (422): 재고 부족
    """
    return await service.add_item(user.id, body)


@router.patch(
    "/items/{item_id}",
    response_model=CartResponse,
    status_code=status.HTTP_200_OK,
    summary="장바구니 수량 수정",
)
async def update_item(
    item_id: int,
    body: UpdateCartItemRequest,
    user: User = Depends(get_active_user),
    service: CartService = Depends(get_cart_service),
) -> CartResponse:
    """장바구니 항목 수량 수정.

    Errors:
    - CART_ITEM_NOT_FOUND (404): 항목 없음 또는 타인 소유
    - OUT_OF_STOCK (422): 재고 부족
    """
    return await service.update_item(user.id, item_id, body)


@router.delete(
    "/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="장바구니 단건 삭제",
)
async def remove_item(
    item_id: int,
    user: User = Depends(get_active_user),
    service: CartService = Depends(get_cart_service),
) -> None:
    """장바구니 항목 단건 삭제.

    Errors:
    - CART_ITEM_NOT_FOUND (404): 항목 없음 또는 타인 소유
    """
    await service.remove_item(user.id, item_id)


@router.post(
    "/items/bulk-delete",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="장바구니 일괄 삭제",
)
async def bulk_remove(
    body: BulkDeleteRequest,
    user: User = Depends(get_active_user),
    service: CartService = Depends(get_cart_service),
) -> None:
    """장바구니 항목 일괄 삭제. user_id 조건으로 타인 항목 삭제 차단."""
    await service.bulk_remove(user.id, body.item_ids)
