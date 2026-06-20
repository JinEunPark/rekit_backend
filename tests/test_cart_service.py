"""cart 서비스 단위 테스트 — FakeCartRepository (in-memory) 사용.

DB 없이 서비스 로직을 검증한다:
- 빈 장바구니 조회
- 신규 상품 담기
- 같은 상품 재담기 → 수량 합산
- INACTIVE 상품 담기 → ProductNotFound
- 재고 부족 담기 → OutOfStock
- 수량 수정
- 타인 항목 수정 → CartItemNotFound
- 단건 삭제
- 금액 계산 (subtotal, items_total, total)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.cart.cart_schemas import (
    AddToCartRequest,
    UpdateCartItemRequest,
)
from app.cart.cart_service import CartService, _SHIPPING_FEE_ESTIMATE
from app.cart.models import CartItem
from app.catalog.models import (
    ConditionGrade,
    Product,
    ProductCategory,
    ProductImage,
    ProductStatus,
)
from app.core.exceptions import CartItemNotFound, OutOfStock, ProductNotFound

# ── 팩토리 ──────────────────────────────────────────────────────


def make_product(
    *,
    product_id: int = 1,
    price: int = 300_000,
    stock: int = 5,
    status: ProductStatus = ProductStatus.ACTIVE,
    images: list[ProductImage] | None = None,
) -> Product:
    p = Product(
        title="테스트 냉장고",
        description="",
        category=ProductCategory.REFRIGERATOR,
        condition_grade=ConditionGrade.A,
        warranty_works=True,
        price=price,
        stock=stock,
        status=status,
    )
    p.id = product_id
    p.created_at = datetime.now(UTC)
    p.updated_at = datetime.now(UTC)
    # Product.images 는 relationship — 메모리에서 직접 할당
    p.images = list(images or [])
    return p


def make_image(*, url: str = "https://cdn.example.com/img.jpg") -> ProductImage:
    img = ProductImage(url=url, sort_order=0)
    img.id = 1
    return img


def make_cart_item(
    *,
    item_id: int = 1,
    user_id: int = 1,
    product: Product,
    quantity: int = 1,
) -> CartItem:
    item = CartItem(user_id=user_id, product_id=product.id, quantity=quantity)
    item.id = item_id
    item.product = product  # type: ignore[assignment]
    item.created_at = datetime.now(UTC)
    item.updated_at = datetime.now(UTC)
    return item


# ── Fake Repository ──────────────────────────────────────────────


class FakeCartRepository:
    """Python list 기반 CartRepository 시뮬레이션.

    실제 DB 없이 서비스 로직만 격리 검증하기 위한 test double.
    """

    def __init__(
        self,
        items: list[CartItem] | None = None,
        products: list[Product] | None = None,
    ) -> None:
        self._items: list[CartItem] = list(items or [])
        self._products: list[Product] = list(products or [])
        self._next_id = max((i.id for i in self._items), default=0) + 1

    async def get_all_by_user_id(self, user_id: int) -> list[CartItem]:
        return [i for i in self._items if i.user_id == user_id]

    async def get_by_id(self, item_id: int) -> CartItem | None:
        return next((i for i in self._items if i.id == item_id), None)

    async def get_by_user_and_product(
        self, user_id: int, product_id: int
    ) -> CartItem | None:
        return next(
            (
                i
                for i in self._items
                if i.user_id == user_id and i.product_id == product_id
            ),
            None,
        )

    async def save(self, item: CartItem) -> CartItem:
        if not any(i.id == item.id for i in self._items):
            item.id = self._next_id
            self._next_id += 1
            self._items.append(item)
        return item

    async def delete(self, item: CartItem) -> None:
        self._items = [i for i in self._items if i.id != item.id]

    async def delete_by_ids(self, user_id: int, item_ids: list[int]) -> None:
        self._items = [
            i
            for i in self._items
            if not (i.id in item_ids and i.user_id == user_id)
        ]

    async def get_product(self, product_id: int) -> Product | None:
        return next((p for p in self._products if p.id == product_id), None)


# ── 헬퍼 ────────────────────────────────────────────────────────


def _make_service(
    items: list[CartItem] | None = None,
    products: list[Product] | None = None,
) -> CartService:
    repo = FakeCartRepository(items=items, products=products)
    return CartService(repo)  # type: ignore[arg-type]


# ── get_cart ─────────────────────────────────────────────────────


async def test_get_cart_empty() -> None:
    """빈 장바구니 → items=[], summary.items_total=0."""
    service = _make_service()

    result = await service.get_cart(user_id=1)

    assert result.items == []
    assert result.summary.items_total == 0
    assert result.summary.shipping_fee_estimate == _SHIPPING_FEE_ESTIMATE
    assert result.summary.total == _SHIPPING_FEE_ESTIMATE


# ── add_item ──────────────────────────────────────────────────────


async def test_add_item_creates_new() -> None:
    """새 상품 담기 → cart 에 항목 추가됨."""
    product = make_product(product_id=1, price=200_000, stock=3)
    service = _make_service(products=[product])

    result = await service.add_item(user_id=1, data=AddToCartRequest(product_id=1, quantity=1))

    assert len(result.items) == 1
    assert result.items[0].product.id == 1
    assert result.items[0].quantity == 1


async def test_add_item_increments_existing() -> None:
    """같은 상품 재담기 → quantity 합산."""
    product = make_product(product_id=1, price=200_000, stock=5)
    existing = make_cart_item(item_id=1, user_id=1, product=product, quantity=2)
    service = _make_service(items=[existing], products=[product])

    result = await service.add_item(user_id=1, data=AddToCartRequest(product_id=1, quantity=2))

    assert len(result.items) == 1
    assert result.items[0].quantity == 4


async def test_add_item_inactive_product_raises() -> None:
    """INACTIVE 상품 담기 → ProductNotFound."""
    product = make_product(product_id=1, status=ProductStatus.INACTIVE)
    service = _make_service(products=[product])

    with pytest.raises(ProductNotFound):
        await service.add_item(user_id=1, data=AddToCartRequest(product_id=1, quantity=1))


async def test_add_item_sold_out_product_raises() -> None:
    """SOLD_OUT 상품 담기 → ProductNotFound."""
    product = make_product(product_id=1, status=ProductStatus.SOLD_OUT)
    service = _make_service(products=[product])

    with pytest.raises(ProductNotFound):
        await service.add_item(user_id=1, data=AddToCartRequest(product_id=1, quantity=1))


async def test_add_item_nonexistent_product_raises() -> None:
    """존재하지 않는 상품 담기 → ProductNotFound."""
    service = _make_service(products=[])

    with pytest.raises(ProductNotFound):
        await service.add_item(user_id=1, data=AddToCartRequest(product_id=999, quantity=1))


async def test_add_item_out_of_stock_raises() -> None:
    """재고(2) 보다 많은 수량(3) 담기 → OutOfStock."""
    product = make_product(product_id=1, stock=2)
    service = _make_service(products=[product])

    with pytest.raises(OutOfStock):
        await service.add_item(user_id=1, data=AddToCartRequest(product_id=1, quantity=3))


async def test_add_item_existing_exceeds_stock_raises() -> None:
    """기존 수량(3) + 추가 수량(2) > 재고(4) → OutOfStock."""
    product = make_product(product_id=1, stock=4)
    existing = make_cart_item(item_id=1, user_id=1, product=product, quantity=3)
    service = _make_service(items=[existing], products=[product])

    with pytest.raises(OutOfStock):
        await service.add_item(user_id=1, data=AddToCartRequest(product_id=1, quantity=2))


# ── update_item ────────────────────────────────────────────────────


async def test_update_item_quantity() -> None:
    """수량 변경 → 반영됨."""
    product = make_product(product_id=1, stock=10)
    item = make_cart_item(item_id=1, user_id=1, product=product, quantity=1)
    service = _make_service(items=[item], products=[product])

    result = await service.update_item(
        user_id=1, item_id=1, data=UpdateCartItemRequest(quantity=5)
    )

    assert result.items[0].quantity == 5


async def test_update_item_wrong_owner_raises() -> None:
    """타인(user_id=2) 항목 수정 → CartItemNotFound."""
    product = make_product(product_id=1, stock=10)
    item = make_cart_item(item_id=1, user_id=2, product=product, quantity=1)
    service = _make_service(items=[item], products=[product])

    with pytest.raises(CartItemNotFound):
        await service.update_item(
            user_id=1, item_id=1, data=UpdateCartItemRequest(quantity=3)
        )


async def test_update_item_not_found_raises() -> None:
    """존재하지 않는 항목 수정 → CartItemNotFound."""
    service = _make_service()

    with pytest.raises(CartItemNotFound):
        await service.update_item(
            user_id=1, item_id=999, data=UpdateCartItemRequest(quantity=2)
        )


async def test_update_item_out_of_stock_raises() -> None:
    """수정 수량이 재고 초과 → OutOfStock."""
    product = make_product(product_id=1, stock=3)
    item = make_cart_item(item_id=1, user_id=1, product=product, quantity=1)
    service = _make_service(items=[item], products=[product])

    with pytest.raises(OutOfStock):
        await service.update_item(
            user_id=1, item_id=1, data=UpdateCartItemRequest(quantity=5)
        )


# ── remove_item ────────────────────────────────────────────────────


async def test_remove_item() -> None:
    """단건 삭제 후 빈 장바구니."""
    product = make_product(product_id=1)
    item = make_cart_item(item_id=1, user_id=1, product=product)
    service = _make_service(items=[item])

    await service.remove_item(user_id=1, item_id=1)

    cart = await service.get_cart(user_id=1)
    assert cart.items == []


async def test_remove_item_wrong_owner_raises() -> None:
    """타인 항목 삭제 시도 → CartItemNotFound."""
    product = make_product(product_id=1)
    item = make_cart_item(item_id=1, user_id=2, product=product)
    service = _make_service(items=[item])

    with pytest.raises(CartItemNotFound):
        await service.remove_item(user_id=1, item_id=1)


# ── bulk_remove ────────────────────────────────────────────────────


async def test_bulk_remove_deletes_own_items() -> None:
    """일괄 삭제 — 본인 항목만 삭제됨."""
    product = make_product(product_id=1)
    item1 = make_cart_item(item_id=1, user_id=1, product=product)
    item2 = make_cart_item(item_id=2, user_id=1, product=product)
    service = _make_service(items=[item1, item2])

    await service.bulk_remove(user_id=1, item_ids=[1, 2])

    cart = await service.get_cart(user_id=1)
    assert cart.items == []


async def test_bulk_remove_ignores_others_items() -> None:
    """일괄 삭제 — 타인(user_id=2) 항목은 삭제되지 않음."""
    product = make_product(product_id=1)
    item_mine = make_cart_item(item_id=1, user_id=1, product=product)
    item_other = make_cart_item(item_id=2, user_id=2, product=product)
    repo = FakeCartRepository(items=[item_mine, item_other])
    service = CartService(repo)  # type: ignore[arg-type]

    await service.bulk_remove(user_id=1, item_ids=[1, 2])

    # user 2 의 항목은 살아있어야 한다
    assert any(i.id == 2 for i in repo._items)


# ── cart summary ───────────────────────────────────────────────────


async def test_cart_summary_computation() -> None:
    """subtotal, items_total, total 계산 검증.

    상품A: price=200_000, qty=2 → subtotal=400_000
    상품B: price=150_000, qty=1 → subtotal=150_000
    items_total = 550_000
    total = 550_000 + 60_000 = 610_000
    """
    productA = make_product(product_id=1, price=200_000, stock=5)
    productB = make_product(product_id=2, price=150_000, stock=5)
    itemA = make_cart_item(item_id=1, user_id=1, product=productA, quantity=2)
    itemB = make_cart_item(item_id=2, user_id=1, product=productB, quantity=1)
    service = _make_service(items=[itemA, itemB])

    result = await service.get_cart(user_id=1)

    subtotals = {r.product.id: r.subtotal for r in result.items}
    assert subtotals[1] == 400_000
    assert subtotals[2] == 150_000
    assert result.summary.items_total == 550_000
    assert result.summary.shipping_fee_estimate == _SHIPPING_FEE_ESTIMATE
    assert result.summary.total == 550_000 + _SHIPPING_FEE_ESTIMATE


async def test_cart_item_thumbnail_from_first_image() -> None:
    """thumbnail_url = images[0].url."""
    img = make_image(url="https://cdn.example.com/front.jpg")
    product = make_product(product_id=1, images=[img])
    item = make_cart_item(item_id=1, user_id=1, product=product)
    service = _make_service(items=[item])

    result = await service.get_cart(user_id=1)

    assert result.items[0].product.thumbnail_url == "https://cdn.example.com/front.jpg"


async def test_cart_item_thumbnail_none_when_no_images() -> None:
    """이미지 없는 상품 → thumbnail_url=None."""
    product = make_product(product_id=1, images=[])
    item = make_cart_item(item_id=1, user_id=1, product=product)
    service = _make_service(items=[item])

    result = await service.get_cart(user_id=1)

    assert result.items[0].product.thumbnail_url is None
