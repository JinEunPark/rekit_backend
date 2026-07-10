"""order 서비스 단위 테스트 — FakeOrderRepository (in-memory) 사용.

DB 없이 서비스 로직을 검증한다:
  - 견적(get_quote): 배송비 계산, 직배송 가능 여부
  - 주문 생성(create_order): 본인인증, 재고, order_number 포맷
  - 주문 조회/목록/취소 흐름
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.address.models import Address
from app.catalog.models import ConditionGrade, Product, ProductStatus
from app.core.exceptions import (
    AddressNotFoundError,
    IdentityRequiredError,
    OrderCancelForbiddenError,
    OrderNotFoundError,
    OutOfStockError,
    PermissionDeniedError,
    ProductUnavailableError,
    RefundForbiddenError,
    ShipmentNotFoundError,
)
from app.order.models import Order, OrderItem, OrderStatus
from app.order.order_schemas import (
    CreateOrderRequest,
    OrderItemRequest,
    QuoteRequest,
)
from app.order.order_service import OrderService
from app.order.shipment import Shipment, ShipmentMethod, ShipmentStatus

# ── 팩토리 ──────────────────────────────────────────────────────────


def make_product(
    *,
    product_id: int = 1,
    price: int = 300_000,
    stock: int = 5,
    status: ProductStatus = ProductStatus.ACTIVE,
    brand: str | None = "LG전자",
    model_name: str | None = "F21VDAP",
) -> Product:
    """테스트용 Product 인스턴스 (DB 없이 메모리)."""
    p = Product(
        title="LG 냉장고 500L",
        description="상태 양호",
        category="REFRIGERATOR",
        condition_grade=ConditionGrade.B,
        price=price,
        stock=stock,
        status=status,
    )
    p.id = product_id
    p.brand = brand
    p.model_name = model_name
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


def make_shipment(
    *,
    order_id: int = 1,
    method: ShipmentMethod = ShipmentMethod.PARCEL,
    status: ShipmentStatus = ShipmentStatus.PREPARING,
    carrier: str | None = None,
    tracking_number: str | None = None,
) -> Shipment:
    s = Shipment(
        order_id=order_id,
        method=method,
        status=status,
        carrier=carrier,
        tracking_number=tracking_number,
    )
    s.id = order_id
    return s


# ── FakeOrderRepository ─────────────────────────────────────────────


class FakeOrderRepository:
    """in-memory Fake. 실제 DB 쿼리를 흉내낸다."""

    def __init__(
        self,
        *,
        products: list[Product] | None = None,
        addresses: list[Address] | None = None,
        orders: list[Order] | None = None,
        shipments: list[Shipment] | None = None,
        locked_order_override: Order | None = None,
    ) -> None:
        self._products: dict[int, Product] = {p.id: p for p in (products or [])}
        self._addresses: list[Address] = addresses or []
        self._orders: list[Order] = orders or []
        self._shipments: list[Shipment] = shipments or []
        self._next_order_id = 100
        self.increment_calls: list[tuple[int, int]] = []
        self.locked_read_calls: int = 0
        self.unlocked_read_calls: int = 0
        # get_by_order_number_with_lock 이 반환할 주문을 강제 지정 (테스트 spy용)
        self._locked_order_override: Order | None = locked_order_override

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
        self.unlocked_read_calls += 1
        return next((o for o in self._orders if o.order_number == order_number), None)

    async def get_by_order_number_with_lock(self, order_number: str) -> Order | None:
        self.locked_read_calls += 1
        if self._locked_order_override is not None:
            return self._locked_order_override
        return next((o for o in self._orders if o.order_number == order_number), None)

    async def get_by_order_number_with_shipment(self, order_number: str) -> Order | None:
        order = next((o for o in self._orders if o.order_number == order_number), None)
        if order is None:
            return None
        order.shipment = next((s for s in self._shipments if s.order_id == order.id), None)
        return order

    async def get_product(self, product_id: int) -> Product | None:
        return self._products.get(product_id)

    async def get_product_with_lock(self, product_id: int) -> Product | None:
        return self._products.get(product_id)

    async def get_products_with_lock(
        self, product_ids: list[int]
    ) -> dict[int, Product]:
        return {pid: self._products[pid] for pid in product_ids if pid in self._products}

    async def get_address_by_id(self, address_id: int) -> Address | None:
        return next((a for a in self._addresses if a.id == address_id), None)

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

    async def increment_stock(self, product_id: int, quantity: int) -> None:
        self.increment_calls.append((product_id, quantity))
        if product_id in self._products:
            self._products[product_id].stock += quantity


# ── 헬퍼 ────────────────────────────────────────────────────────────


def _make_service(
    *,
    products: list[Product] | None = None,
    addresses: list[Address] | None = None,
    orders: list[Order] | None = None,
    shipments: list[Shipment] | None = None,
) -> OrderService:
    repo = FakeOrderRepository(
        products=products, addresses=addresses, orders=orders, shipments=shipments
    )
    return OrderService(repo)  # type: ignore[arg-type]


# ── get_quote ────────────────────────────────────────────────────────


class TestGetQuote:
    async def test_get_quote_freight(self) -> None:
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

    async def test_get_quote_direct_available(self) -> None:
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

    async def test_get_quote_direct_unavailable(self) -> None:
        """DIRECT 배송 + 지방 zipcode → direct_available=False, 예외 발생."""
        product = make_product(price=300_000, stock=5)
        address = make_address(zipcode="50000")  # 경남 — DIRECT 불가
        service = _make_service(products=[product], addresses=[address])

        req = QuoteRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.DIRECT,
        )
        with pytest.raises(OrderCancelForbiddenError):
            await service.get_quote(user_id=1, req=req)

    async def test_get_quote_address_not_found(self) -> None:
        """존재하지 않는 address_id → AddressNotFoundError (404)."""
        product = make_product()
        service = _make_service(products=[product], addresses=[])

        req = QuoteRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=99,
            shipping_method=ShipmentMethod.PARCEL,
        )
        with pytest.raises(AddressNotFoundError):
            await service.get_quote(user_id=1, req=req)

    async def test_get_quote_address_not_owned_returns_403(self) -> None:
        """address 존재하지만 다른 user 소유 → PermissionDeniedError (403)."""
        product = make_product()
        address = make_address(user_id=99)
        service = _make_service(products=[product], addresses=[address])

        req = QuoteRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        with pytest.raises(PermissionDeniedError):
            await service.get_quote(user_id=1, req=req)

    async def test_get_quote_inactive_product_raises_product_unavailable(self) -> None:
        """견적 시 INACTIVE 상품 → ProductUnavailableError (400)."""
        product = make_product(status=ProductStatus.INACTIVE)
        address = make_address()
        service = _make_service(products=[product], addresses=[address])

        req = QuoteRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        with pytest.raises(ProductUnavailableError):
            await service.get_quote(user_id=1, req=req)


# ── create_order ─────────────────────────────────────────────────────


class TestCreateOrder:
    async def test_create_order_requires_identity(self) -> None:
        """identity_verified=False → IdentityRequiredError."""
        product = make_product()
        address = make_address()
        service = _make_service(products=[product], addresses=[address])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        with pytest.raises(IdentityRequiredError):
            await service.create_order(user_id=1, req=req, identity_verified=False)

    async def test_create_order_out_of_stock(self) -> None:
        """stock=0 → OutOfStockError."""
        product = make_product(stock=0)
        address = make_address()
        service = _make_service(products=[product], addresses=[address])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        with pytest.raises(OutOfStockError):
            await service.create_order(user_id=1, req=req, identity_verified=True)

    async def test_create_order_success(self) -> None:
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

    async def test_create_order_decrements_stock(self) -> None:
        """주문 성공 → 재고가 quantity 만큼 감소."""
        product = make_product(stock=5)
        address = make_address()
        repo = FakeOrderRepository(products=[product], addresses=[address])
        service = OrderService(repo)  # type: ignore[arg-type]

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=3)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        await service.create_order(user_id=1, req=req, identity_verified=True)

        assert repo._products[1].stock == 2

    async def test_create_order_address_not_found(self) -> None:
        """존재하지 않는 address_id → AddressNotFoundError (404)."""
        product = make_product()
        service = _make_service(products=[product], addresses=[])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=99,
            shipping_method=ShipmentMethod.PARCEL,
        )
        with pytest.raises(AddressNotFoundError):
            await service.create_order(user_id=1, req=req, identity_verified=True)

    async def test_create_order_address_not_owned_returns_403(self) -> None:
        """address 존재하지만 다른 user_id 소유 → PermissionDeniedError (403)."""
        product = make_product()
        address = make_address(user_id=99)  # 다른 사용자 소유
        service = _make_service(products=[product], addresses=[address])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        with pytest.raises(PermissionDeniedError):
            await service.create_order(user_id=1, req=req, identity_verified=True)

    async def test_create_order_inactive_product_raises_product_unavailable(self) -> None:
        """INACTIVE 상품 → ProductUnavailableError (400)."""
        product = make_product(status=ProductStatus.INACTIVE)
        address = make_address()
        service = _make_service(products=[product], addresses=[address])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        with pytest.raises(ProductUnavailableError):
            await service.create_order(user_id=1, req=req, identity_verified=True)

    async def test_create_order_sold_out_product_raises_product_unavailable(self) -> None:
        """SOLD_OUT 상품 → ProductUnavailableError (400)."""
        product = make_product(status=ProductStatus.SOLD_OUT, stock=0)
        address = make_address()
        service = _make_service(products=[product], addresses=[address])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        with pytest.raises(ProductUnavailableError):
            await service.create_order(user_id=1, req=req, identity_verified=True)

    async def test_create_order_stores_brand_snapshot(self) -> None:
        """주문 생성 시 상품 브랜드가 스냅샷으로 저장된다."""
        product = make_product(brand="삼성전자")
        address = make_address()
        service = _make_service(products=[product], addresses=[address])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        result = await service.create_order(user_id=1, req=req, identity_verified=True)

        assert result.items[0].product_brand_snapshot == "삼성전자"

    async def test_create_order_brand_snapshot_none_when_no_brand(self) -> None:
        """브랜드 미입력 상품 → product_brand_snapshot=None."""
        product = make_product(brand=None)
        address = make_address()
        service = _make_service(products=[product], addresses=[address])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        result = await service.create_order(user_id=1, req=req, identity_verified=True)

        assert result.items[0].product_brand_snapshot is None

    async def test_create_order_stores_model_name_snapshot(self) -> None:
        """주문 생성 시 상품 모델명이 스냅샷으로 저장된다."""
        product = make_product(model_name="F21VDAP")
        address = make_address()
        service = _make_service(products=[product], addresses=[address])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        result = await service.create_order(user_id=1, req=req, identity_verified=True)

        assert result.items[0].product_model_name_snapshot == "F21VDAP"

    async def test_create_order_model_name_snapshot_none_when_no_model_name(self) -> None:
        """모델명 미입력 상품 → product_model_name_snapshot=None."""
        product = make_product(model_name=None)
        address = make_address()
        service = _make_service(products=[product], addresses=[address])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=1)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        result = await service.create_order(user_id=1, req=req, identity_verified=True)

        assert result.items[0].product_model_name_snapshot is None

    async def test_create_order_stock_exactly_enough(self) -> None:
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

    async def test_create_order_stock_insufficient_raises(self) -> None:
        """요청 수량 > 재고 → OutOfStockError."""
        product = make_product(stock=1)
        address = make_address()
        service = _make_service(products=[product], addresses=[address])

        req = CreateOrderRequest(
            items=[OrderItemRequest(product_id=1, quantity=2)],
            address_id=1,
            shipping_method=ShipmentMethod.PARCEL,
        )
        with pytest.raises(OutOfStockError):
            await service.create_order(user_id=1, req=req, identity_verified=True)


# ── cancel_order ─────────────────────────────────────────────────────


class TestCancelOrder:
    async def test_cancel_order_pending(self) -> None:
        """PENDING 주문 → CANCELLED 성공."""
        order = make_order(status=OrderStatus.PENDING)
        service = _make_service(orders=[order])

        result = await service.cancel_order(user_id=1, order_number=order.order_number)

        assert result.status == OrderStatus.CANCELLED
        assert result.cancelled_at is not None

    async def test_cancel_order_paid(self) -> None:
        """PAID 주문도 취소 가능."""
        order = make_order(status=OrderStatus.PAID)
        service = _make_service(orders=[order])

        result = await service.cancel_order(user_id=1, order_number=order.order_number)

        assert result.status == OrderStatus.CANCELLED

    async def test_cancel_order_preparing(self) -> None:
        """PREPARING 주문도 취소 가능."""
        order = make_order(status=OrderStatus.PREPARING)
        service = _make_service(orders=[order])

        result = await service.cancel_order(user_id=1, order_number=order.order_number)

        assert result.status == OrderStatus.CANCELLED

    async def test_cancel_order_forbidden(self) -> None:
        """SHIPPING 상태 → OrderCancelForbiddenError."""
        order = make_order(status=OrderStatus.SHIPPING)
        service = _make_service(orders=[order])

        with pytest.raises(OrderCancelForbiddenError):
            await service.cancel_order(user_id=1, order_number=order.order_number)

    async def test_cancel_order_delivered_forbidden(self) -> None:
        """DELIVERED 상태 → OrderCancelForbiddenError."""
        order = make_order(status=OrderStatus.DELIVERED)
        service = _make_service(orders=[order])

        with pytest.raises(OrderCancelForbiddenError):
            await service.cancel_order(user_id=1, order_number=order.order_number)

    async def test_cancel_order_cancelled_forbidden(self) -> None:
        """이미 CANCELLED 상태 → OrderCancelForbiddenError."""
        order = make_order(status=OrderStatus.CANCELLED)
        service = _make_service(orders=[order])

        with pytest.raises(OrderCancelForbiddenError):
            await service.cancel_order(user_id=1, order_number=order.order_number)

    async def test_cancel_order_refunded_forbidden(self) -> None:
        """REFUNDED 상태 → OrderCancelForbiddenError."""
        order = make_order(status=OrderStatus.REFUNDED)
        service = _make_service(orders=[order])

        with pytest.raises(OrderCancelForbiddenError):
            await service.cancel_order(user_id=1, order_number=order.order_number)

    async def test_cancel_order_restores_stock_for_single_item(self) -> None:
        """취소 시 주문 라인의 재고가 복구된다."""
        order = make_order(status=OrderStatus.PENDING)
        order.items = [
            OrderItem(
                product_id=1,
                product_title_snapshot="상품",
                price_snapshot=100_000,
                quantity=2,
            )
        ]
        repo = FakeOrderRepository(orders=[order])
        service = OrderService(repo)  # type: ignore[arg-type]

        await service.cancel_order(user_id=1, order_number=order.order_number)

        assert repo.increment_calls == [(1, 2)]

    async def test_cancel_order_restores_stock_for_multiple_items(self) -> None:
        """라인이 여러 개면 각 상품별로 정확한 수량만큼 복구된다."""
        order = make_order(status=OrderStatus.PENDING)
        order.items = [
            OrderItem(
                product_id=1,
                product_title_snapshot="상품A",
                price_snapshot=100_000,
                quantity=1,
            ),
            OrderItem(
                product_id=2,
                product_title_snapshot="상품B",
                price_snapshot=50_000,
                quantity=3,
            ),
        ]
        repo = FakeOrderRepository(orders=[order])
        service = OrderService(repo)  # type: ignore[arg-type]

        await service.cancel_order(user_id=1, order_number=order.order_number)

        assert repo.increment_calls == [(1, 1), (2, 3)]

    async def test_cancel_already_cancelled_order_does_not_double_restore(self) -> None:
        """이미 취소된 주문을 다시 취소 시도하면 재고 복구가 중복되지 않는다."""
        order = make_order(status=OrderStatus.CANCELLED)
        order.items = [
            OrderItem(
                product_id=1,
                product_title_snapshot="상품",
                price_snapshot=100_000,
                quantity=2,
            )
        ]
        repo = FakeOrderRepository(orders=[order])
        service = OrderService(repo)  # type: ignore[arg-type]

        with pytest.raises(OrderCancelForbiddenError):
            await service.cancel_order(user_id=1, order_number=order.order_number)

        assert repo.increment_calls == []

    async def test_cancel_paid_order_also_restores_stock(self) -> None:
        """결제 후(PAID) 취소도 재고는 복구된다 (PG 환불은 별도 처리)."""
        order = make_order(status=OrderStatus.PAID)
        order.items = [
            OrderItem(
                product_id=1,
                product_title_snapshot="상품",
                price_snapshot=100_000,
                quantity=1,
            )
        ]
        repo = FakeOrderRepository(orders=[order])
        service = OrderService(repo)  # type: ignore[arg-type]

        await service.cancel_order(user_id=1, order_number=order.order_number)

        assert repo.increment_calls == [(1, 1)]

    async def test_cancel_order_uses_locked_read(self) -> None:
        """cancel_order 는 락 버전 조회를 정확히 1회 사용하고, 락 없는 버전은 사용하지 않는다."""
        # Arrange
        order = make_order(status=OrderStatus.PENDING)
        repo = FakeOrderRepository(orders=[order])
        service = OrderService(repo)  # type: ignore[arg-type]

        # Act
        await service.cancel_order(user_id=1, order_number=order.order_number)

        # Assert
        assert repo.locked_read_calls == 1
        assert repo.unlocked_read_calls == 0


# ── list_orders ──────────────────────────────────────────────────────


class TestListOrders:
    async def test_list_orders_empty(self) -> None:
        """주문이 없을 때 items=[] 이고 meta.total=0, total_pages=0."""
        service = _make_service(orders=[])

        result = await service.list_orders(user_id=1, page=1, size=20)

        assert result.items == []
        assert result.meta.total == 0
        assert result.meta.total_pages == 0
        assert result.meta.page == 1
        assert result.meta.size == 20
        # 직렬화 시에도 null 이 아닌 [] 임을 확인
        dumped = result.model_dump()
        assert isinstance(dumped["items"], list)

    async def test_list_orders_returns_user_orders_only(self) -> None:
        """다른 user_id 주문은 노출 안 됨."""
        my_order = make_order(order_id=1, user_id=1)
        other_order = make_order(order_id=2, user_id=2)
        other_order.order_number = "RK-TEST0002"
        service = _make_service(orders=[my_order, other_order])

        result = await service.list_orders(user_id=1, page=1, size=20)

        assert result.meta.total == 1

    async def test_list_orders_pagination(self) -> None:
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
    async def test_get_order_not_found(self) -> None:
        """없는 order_number → OrderNotFoundError."""
        service = _make_service(orders=[])

        with pytest.raises(OrderNotFoundError):
            await service.get_order(user_id=1, order_number="RK-NOTEXIST")

    async def test_get_order_wrong_owner(self) -> None:
        """타인의 주문 조회 → OrderNotFoundError (정보 노출 방지)."""
        order = make_order(user_id=2)
        service = _make_service(orders=[order])

        with pytest.raises(OrderNotFoundError):
            await service.get_order(user_id=1, order_number=order.order_number)

    async def test_get_order_success(self) -> None:
        """본인 주문 조회 성공."""
        order = make_order(user_id=1)
        service = _make_service(orders=[order])

        result = await service.get_order(user_id=1, order_number=order.order_number)

        assert result.order_number == order.order_number


# ── get_shipment ──────────────────────────────────────────────────────


class TestGetShipment:
    async def test_get_shipment_success(self) -> None:
        """배송 정보 존재 → ShipmentResponse 반환."""
        order = make_order(order_id=1, user_id=1)
        shipment = make_shipment(
            order_id=1,
            method=ShipmentMethod.PARCEL,
            status=ShipmentStatus.IN_TRANSIT,
            carrier="CJ대한통운",
            tracking_number="123456789",
        )
        service = _make_service(orders=[order], shipments=[shipment])

        result = await service.get_shipment(user_id=1, order_number=order.order_number)

        assert result.method == ShipmentMethod.PARCEL
        assert result.status == ShipmentStatus.IN_TRANSIT
        assert result.carrier == "CJ대한통운"
        assert result.tracking_number == "123456789"

    async def test_get_shipment_order_not_found(self) -> None:
        """없는 order_number → OrderNotFoundError."""
        service = _make_service(orders=[])

        with pytest.raises(OrderNotFoundError):
            await service.get_shipment(user_id=1, order_number="RK-NOTEXIST")

    async def test_get_shipment_wrong_owner(self) -> None:
        """타인 주문 조회 → OrderNotFoundError."""
        order = make_order(order_id=1, user_id=2)
        shipment = make_shipment(order_id=1)
        service = _make_service(orders=[order], shipments=[shipment])

        with pytest.raises(OrderNotFoundError):
            await service.get_shipment(user_id=1, order_number=order.order_number)

    async def test_get_shipment_not_created_yet(self) -> None:
        """주문은 있지만 배송 정보 미생성 → ShipmentNotFoundError."""
        order = make_order(order_id=1, user_id=1)
        service = _make_service(orders=[order], shipments=[])

        with pytest.raises(ShipmentNotFoundError):
            await service.get_shipment(user_id=1, order_number=order.order_number)


# ── request_refund ────────────────────────────────────────────────────


class TestRequestRefund:
    async def test_request_refund_delivered_success(self) -> None:
        """DELIVERED 주문 → REFUNDED 전환, cancelled_at 기록."""
        order = make_order(order_id=1, user_id=1, status=OrderStatus.DELIVERED)
        service = _make_service(orders=[order])

        result = await service.request_refund(user_id=1, order_number=order.order_number)

        assert result.status == OrderStatus.REFUNDED
        assert result.cancelled_at is not None

    async def test_request_refund_non_delivered_forbidden(self) -> None:
        """DELIVERED 가 아닌 상태 → RefundForbiddenError."""
        for bad_status in (
            OrderStatus.PENDING,
            OrderStatus.PAID,
            OrderStatus.PREPARING,
            OrderStatus.SHIPPING,
            OrderStatus.CANCELLED,
        ):
            order = make_order(order_id=1, user_id=1, status=bad_status)
            order.order_number = f"RK-TEST{bad_status.value}"
            service = _make_service(orders=[order])

            with pytest.raises(RefundForbiddenError):
                await service.request_refund(user_id=1, order_number=order.order_number)

    async def test_request_refund_order_not_found(self) -> None:
        """없는 order_number → OrderNotFoundError."""
        service = _make_service(orders=[])

        with pytest.raises(OrderNotFoundError):
            await service.request_refund(user_id=1, order_number="RK-NOTEXIST")

    async def test_request_refund_wrong_owner(self) -> None:
        """타인 주문 환불 요청 → OrderNotFoundError."""
        order = make_order(order_id=1, user_id=2, status=OrderStatus.DELIVERED)
        service = _make_service(orders=[order])

        with pytest.raises(OrderNotFoundError):
            await service.request_refund(user_id=1, order_number=order.order_number)


# ── Task 2: PENDING 주문 타임아웃 지연 평가 ────────────────────────────


class TestExpireAbandonedOrder:
    async def test_get_order_expires_pending_order_past_timeout(self) -> None:
        """31분이 지난 PENDING 주문은 get_order 시 즉시 CANCELLED 로 전환된다."""
        order = make_order(user_id=1, status=OrderStatus.PENDING)
        order.created_at = datetime.now(UTC) - timedelta(minutes=31)
        order.items = []
        service = _make_service(orders=[order])

        result = await service.get_order(user_id=1, order_number=order.order_number)

        assert result.status == OrderStatus.CANCELLED

    async def test_get_order_does_not_expire_pending_order_within_timeout(self) -> None:
        """30분 미만인 PENDING 주문은 만료되지 않는다."""
        order = make_order(user_id=1, status=OrderStatus.PENDING)
        order.created_at = datetime.now(UTC) - timedelta(minutes=10)
        service = _make_service(orders=[order])

        result = await service.get_order(user_id=1, order_number=order.order_number)

        assert result.status == OrderStatus.PENDING

    async def test_get_order_does_not_expire_non_pending_order(self) -> None:
        """PENDING 이 아닌 주문(PAID 등)은 created_at 이 오래돼도 만료 처리 안 함."""
        order = make_order(user_id=1, status=OrderStatus.PAID)
        order.created_at = datetime.now(UTC) - timedelta(days=999)
        service = _make_service(orders=[order])

        result = await service.get_order(user_id=1, order_number=order.order_number)

        assert result.status == OrderStatus.PAID

    async def test_get_order_expire_double_checks_status_after_lock(self) -> None:
        """락 재조회 결과가 이미 CANCELLED이면 increment_stock을 호출하지 않는다.

        Given: 1차 조회는 PENDING(만료 후보) + 아이템 있음,
        락 재조회는 CANCELLED(다른 트랜잭션이 선점)
        Then:  increment_stock 호출 없음 — 이중 복구 방지

        NOTE: already_cancelled 에 items 를 공유하면 SQLAlchemy relationship이
              아이템을 재배치해 order.items 가 비어 Red 단계를 제대로 못 잡는다.
              별도 status=CANCELLED 주문을 override 로 쓴다.
        """
        # Arrange: 만료 후보 주문 (아이템 있음)
        order = make_order(user_id=1, status=OrderStatus.PENDING, order_id=10)
        order.created_at = datetime.now(UTC) - timedelta(minutes=31)
        order.items = [
            OrderItem(
                product_id=1,
                product_title_snapshot="상품",
                price_snapshot=100_000,
                quantity=2,
            )
        ]

        # 락 재조회 시 CANCELLED 버전 반환 — 아이템 공유 없이 별도 객체 사용
        already_cancelled = make_order(
            user_id=1, status=OrderStatus.CANCELLED, order_id=11
        )
        already_cancelled.order_number = order.order_number

        repo = FakeOrderRepository(
            orders=[order], locked_order_override=already_cancelled
        )
        service = OrderService(repo)  # type: ignore[arg-type]

        # Act
        await service.get_order(user_id=1, order_number=order.order_number)

        # Assert: 락 재조회 후 CANCELLED → increment_stock 호출 없음
        assert repo.increment_calls == []
