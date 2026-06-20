"""order 서비스 단위 테스트 — FakeOrderRepository (in-memory) 사용.

DB 없이 서비스 로직을 검증한다:
  - 견적(get_quote): 배송비 계산, 직배송 가능 여부
  - 주문 생성(create_order): 본인인증, 재고, order_number 포맷
  - 주문 조회/목록/취소 흐름
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.address.models import Address
from app.catalog.models import ConditionGrade, Product, ProductCategory, ProductStatus
from app.core.exceptions import (
    AddressNotFound,
    IdentityRequired,
    OrderCancelForbidden,
    OrderNotFound,
    OutOfStock,
)
from app.order.models import Order, OrderItem, OrderStatus
from app.order.order_schemas import (
    CreateOrderRequest,
    OrderItemRequest,
    QuoteRequest,
)
from app.order.order_service import OrderService
from app.order.shipment import ShipmentMethod

# ── 팩토리 ──────────────────────────────────────────────────────────


def make_product(
    *,
    product_id: int = 1,
    price: int = 300_000,
    stock: int = 5,
    status: ProductStatus = ProductStatus.ACTIVE,
) -> Product:
    """테스트용 Product 인스턴스 (DB 없이 메모리)."""
    p = Product(
        title="LG 냉장고 500L",
        description="상태 양호",
        category=ProductCategory.REFRIGERATOR,
        condition_grade=ConditionGrade.B,
        price=price,
        stock=stock,
        status=status,
    )
    p.id = product_id
    p.images = []
    return p


def make_address(
    *,
    address_id: int = 1,
    user_id: int = 1,
    zipcode: str = "01234",
) -> Address:
    """테스트용 Address 인스턴스."""
    a = Address(
        user_id=user_id,
        recipient="홍길동",
        phone="01012345678",
        zipcode=zipcode,
        address1="서울시 강남구 테헤란로 1",
        is_default=True,
    )
    a.id = address_id
    return a


def make_order(
    *,
    order_id: int = 1,
    user_id: int = 1,
    status: OrderStatus = OrderStatus.PENDING,
) -> Order:
    """테스트용 Order 인스턴스."""
    now = datetime.now(UTC)
    o = Order(
        order_number=f"RK-TEST{order_id:04d}",
        user_id=user_id,
        total_amount=305_000,
        shipping_fee=5_000,
        discount_amount=0,
        shipping_method=ShipmentMethod.PARCEL,
        status=status,
        recipient_name="홍길동",
        recipient_phone="01012345678",
        zipcode="01234",
        address1="서울시 강남구 테헤란로 1",
    )
    o.id = order_id
    o.items = []
    o.created_at = now
    o.updated_at = now
    return o


# ── FakeOrderRepository ─────────────────────────────────────────────


class FakeOrderRepository:
    """in-memory Fake. 실제 DB 쿼리를 흉내낸다."""

    def __init__(
        self,
        *,
        products: list[Product] | None = None,
        addresses: list[Address] | None = None,
        orders: list[Order] | None = None,
    ) -> None:
        self._products: dict[int, Product] = {p.id: p for p in (products or [])}
        self._addresses: list[Address] = addresses or []
        self._orders: list[Order] = orders or []
        self._next_order_id = 100

    # ── 필수 인터페이스 ────────────────────────────────────

    async def get_list_by_user(
        self, user_id: int, page: int, size: int
    ) -> tuple[list[Order], int]:
        matched = [o for o in self._orders if o.user_id == user_id]
        # 최신순 정렬 (created_at 내림차순)
        matched.sort(key=lambda o: o.created_at, reverse=True)
        total = len(matched)
        offset = (page - 1) * size
        return matched[offset : offset + size], total

    async def get_by_order_number(self, order_number: str) -> Order | None:
        return next((o for o in self._orders if o.order_number == order_number), None)

    async def get_product_with_lock(self, product_id: int) -> Product | None:
        """Fake: lock 없이 단순 조회."""
        return self._products.get(product_id)

    async def get_address_by_user(self, user_id: int, address_id: int) -> Address | None:
        return next(
            (a for a in self._addresses if a.user_id == user_id and a.id == address_id),
            None,
        )

    async def save(self, order: Order) -> Order:
        order.id = self._next_order_id
        self._next_order_id += 1
        order.created_at = datetime.now(UTC)
        order.updated_at = datetime.now(UTC)
        self._orders.append(order)
        return order

    async def update_order_number(self, order: Order, order_number: str) -> None:
        order.order_number = order_number

    async def decrement_stock(self, product_id: int, quantity: int) -> None:
        if product_id in self._products:
            self._products[product_id].stock -= quantity


# ── 헬퍼 ────────────────────────────────────────────────────────────


def _make_service(
    *,
    products: list[Product] | None = None,
    addresses: list[Address] | None = None,
    orders: list[Order] | None = None,
) -> OrderService:
    repo = FakeOrderRepository(products=products, addresses=addresses, orders=orders)
    return OrderService(repo)


# ── get_quote ────────────────────────────────────────────────────────


class TestGetQuote:
    async def test_get_quote_freight(self):
        """화물택배 선택 → shipping_fee=60000, discount=0."""
        product = make_product(price=300_000, stock=5)
        address = make_address(zipcode="01234")
        service = _make_service(products=[product], addresses=[address])

        req = QuoteRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.FREIGHT,
        )
        result = await service.get_quote(user_id=1, req=req)

        assert result.shipping_fee == 60_000
        assert result.discount_amount == 0
        assert result.items_total == 300_000
        assert result.total_amount == 360_000

    async def test_get_quote_direct_available(self):
        """DIRECT 배송 + 서울 zipcode → direct_available=True, discount=20000."""
        product = make_product(price=300_000, stock=5)
        address = make_address(zipcode="01234")  # 서울 prefix
        service = _make_service(products=[product], addresses=[address])

        req = QuoteRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.DIRECT,
        )
        result = await service.get_quote(user_id=1, req=req)

        assert result.direct_available is True
        assert result.shipping_fee == 40_000
        assert result.discount_amount == 20_000
        assert result.total_amount == 300_000 + 40_000 - 20_000

    async def test_get_quote_direct_unavailable(self):
        """DIRECT 배송 + 지방 zipcode → direct_available=False, 예외 발생."""
        product = make_product(price=300_000, stock=5)
        address = make_address(zipcode="50000")  # 경남 — DIRECT 불가
        service = _make_service(products=[product], addresses=[address])

        req = QuoteRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.DIRECT,
        )
        with pytest.raises(Exception):
            await service.get_quote(user_id=1, req=req)

    async def test_get_quote_address_not_found(self):
        """존재하지 않는 address_id → AddressNotFound."""
        product = make_product()
        service = _make_service(products=[product], addresses=[])

        req = QuoteRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=99,
            shipping_method=ShipmentMethod.PARCEL,
        )
        with pytest.raises(AddressNotFound):
            await service.get_quote(user_id=1, req=req)


# ── create_order ─────────────────────────────────────────────────────


class TestCreateOrder:
    async def test_create_order_requires_identity(self):
        """identity_verified=False → IdentityRequired."""
        product = make_product()
        address = make_address()
        service = _make_service(products=[product], addresses=[address])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        with pytest.raises(IdentityRequired):
            await service.create_order(user_id=1, req=req, identity_verified=False)

    async def test_create_order_out_of_stock(self):
        """stock=0 → OutOfStock."""
        product = make_product(stock=0)
        address = make_address()
        service = _make_service(products=[product], addresses=[address])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        with pytest.raises(OutOfStock):
            await service.create_order(user_id=1, req=req, identity_verified=True)

    async def test_create_order_success(self):
        """정상 주문 → order_number RK-YYMMDD#### 포맷, 재고 감소."""
        product = make_product(price=300_000, stock=5)
        address = make_address()
        service = _make_service(products=[product], addresses=[address])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=2)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        result = await service.create_order(user_id=1, req=req, identity_verified=True)

        # order_number 포맷: RK-YYMMDD + 4자리 숫자
        import re
        assert re.match(r"^RK-\d{6}\d{4}$", result.order_number)
        # 스냅샷 금액
        assert result.total_amount == 300_000 * 2 + 5_000  # items + PARCEL fee
        assert result.shipping_fee == 5_000
        assert result.discount_amount == 0
        # 아이템 수량
        assert len(result.items) == 1
        assert result.items[0].quantity == 2
        assert result.items[0].subtotal == 600_000

    async def test_create_order_decrements_stock(self):
        """주문 성공 → 재고가 quantity 만큼 감소."""
        product = make_product(stock=5)
        address = make_address()
        repo = FakeOrderRepository(products=[product], addresses=[address])
        service = OrderService(repo)

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=3)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        await service.create_order(user_id=1, req=req, identity_verified=True)

        assert repo._products[1].stock == 2

    async def test_create_order_address_not_owned(self):
        """다른 user_id 소유 address → AddressNotFound."""
        product = make_product()
        address = make_address(user_id=99)  # 다른 사용자
        service = _make_service(products=[product], addresses=[address])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        with pytest.raises(AddressNotFound):
            await service.create_order(user_id=1, req=req, identity_verified=True)

    async def test_create_order_stock_exactly_enough(self):
        """재고 == 요청 수량 → 성공."""
        product = make_product(stock=2)
        address = make_address()
        service = _make_service(products=[product], addresses=[address])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=2)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        result = await service.create_order(user_id=1, req=req, identity_verified=True)
        assert result is not None

    async def test_create_order_stock_insufficient_raises(self):
        """요청 수량 > 재고 → OutOfStock."""
        product = make_product(stock=1)
        address = make_address()
        service = _make_service(products=[product], addresses=[address])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=2)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        with pytest.raises(OutOfStock):
            await service.create_order(user_id=1, req=req, identity_verified=True)


# ── cancel_order ─────────────────────────────────────────────────────


class TestCancelOrder:
    async def test_cancel_order_pending(self):
        """PENDING 주문 → CANCELLED 성공."""
        order = make_order(status=OrderStatus.PENDING)
        service = _make_service(orders=[order])

        result = await service.cancel_order(user_id=1, order_number=order.order_number)

        assert result.status == OrderStatus.CANCELLED
        assert result.cancelled_at is not None

    async def test_cancel_order_paid(self):
        """PAID 주문도 취소 가능."""
        order = make_order(status=OrderStatus.PAID)
        service = _make_service(orders=[order])

        result = await service.cancel_order(user_id=1, order_number=order.order_number)

        assert result.status == OrderStatus.CANCELLED

    async def test_cancel_order_preparing(self):
        """PREPARING 주문도 취소 가능."""
        order = make_order(status=OrderStatus.PREPARING)
        service = _make_service(orders=[order])

        result = await service.cancel_order(user_id=1, order_number=order.order_number)

        assert result.status == OrderStatus.CANCELLED

    async def test_cancel_order_forbidden(self):
        """SHIPPING 상태 → OrderCancelForbidden."""
        order = make_order(status=OrderStatus.SHIPPING)
        service = _make_service(orders=[order])

        with pytest.raises(OrderCancelForbidden):
            await service.cancel_order(user_id=1, order_number=order.order_number)

    async def test_cancel_order_delivered_forbidden(self):
        """DELIVERED 상태 → OrderCancelForbidden."""
        order = make_order(status=OrderStatus.DELIVERED)
        service = _make_service(orders=[order])

        with pytest.raises(OrderCancelForbidden):
            await service.cancel_order(user_id=1, order_number=order.order_number)


# ── list_orders ──────────────────────────────────────────────────────


class TestListOrders:
    async def test_list_orders_empty(self):
        """주문이 없을 때 빈 목록 반환."""
        service = _make_service(orders=[])

        result = await service.list_orders(user_id=1, page=1, size=20)

        assert result.items == []
        assert result.meta.total == 0

    async def test_list_orders_returns_user_orders_only(self):
        """다른 user_id 주문은 노출 안 됨."""
        my_order = make_order(order_id=1, user_id=1)
        other_order = make_order(order_id=2, user_id=2)
        other_order.order_number = "RK-TEST0002"
        service = _make_service(orders=[my_order, other_order])

        result = await service.list_orders(user_id=1, page=1, size=20)

        assert result.meta.total == 1

    async def test_list_orders_pagination(self):
        """페이지네이션 메타 정확성."""
        orders = [make_order(order_id=i, user_id=1) for i in range(1, 6)]
        for i, o in enumerate(orders):
            o.order_number = f"RK-TEST{i:04d}"
        service = _make_service(orders=orders)

        result = await service.list_orders(user_id=1, page=1, size=3)

        assert result.meta.total == 5
        assert result.meta.total_pages == 2
        assert len(result.items) == 3


# ── get_order ────────────────────────────────────────────────────────


class TestGetOrder:
    async def test_get_order_not_found(self):
        """없는 order_number → OrderNotFound."""
        service = _make_service(orders=[])

        with pytest.raises(OrderNotFound):
            await service.get_order(user_id=1, order_number="RK-NOTEXIST")

    async def test_get_order_wrong_owner(self):
        """타인의 주문 조회 → OrderNotFound (정보 노출 방지)."""
        order = make_order(user_id=2)
        service = _make_service(orders=[order])

        with pytest.raises(OrderNotFound):
            await service.get_order(user_id=1, order_number=order.order_number)

    async def test_get_order_success(self):
        """본인 주문 조회 성공."""
        order = make_order(user_id=1)
        service = _make_service(orders=[order])

        result = await service.get_order(user_id=1, order_number=order.order_number)

        assert result.order_number == order.order_number
