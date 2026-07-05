"""관리자 주문 서비스 단위 테스트 — AdminOrderService.

DB 없이 fake repo 로 검증한다. AAA 패턴.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.exceptions import OrderNotFoundError
from app.order.admin_order_service import AdminOrderService
from app.order.models import Order, OrderItem, OrderStatus
from app.order.shipment import ShipmentMethod
from app.user.models import User


def _make_order(*, order_number: str = "RK-2607060001") -> Order:
    now = datetime.now(UTC)
    user = User()
    user.id = 1
    user.username = "홍길동"
    user.email = "hong@example.com"

    order = Order()
    order.order_number = order_number
    order.created_at = now
    order.status = OrderStatus.PAID
    order.shipping_method = ShipmentMethod.PARCEL
    order.total_amount = 150_000
    order.shipping_fee = 0
    order.discount_amount = 0
    order.memo = None
    order.user = user
    order.recipient_name = "홍길동"
    order.recipient_phone = "01012345678"
    order.zipcode = "12345"
    order.address1 = "서울시 강남구"
    order.address2 = None
    order.payments = []
    order.paid_at = now
    order.cancelled_at = None
    order.shipment = None

    item = OrderItem()
    item.product_id = 18
    item.product_title_snapshot = "결제테스트 세탁기"
    item.product_brand_snapshot = "LG전자"
    item.product_model_name_snapshot = "F21VDAP"
    item.product_image_url_snapshot = "http://localhost:8333/rekle-images/products/1.jpg"
    item.price_snapshot = 150_000
    item.quantity = 1
    order.items = [item]

    return order


class _FakeAdminOrderRepo:
    def __init__(self, order: Order | None) -> None:
        self._order = order

    async def get_by_order_number(self, order_number: str) -> Order | None:
        if self._order and self._order.order_number == order_number:
            return self._order
        return None


def _make_service(order: Order | None) -> AdminOrderService:
    return AdminOrderService(_FakeAdminOrderRepo(order))  # type: ignore[arg-type]


class TestGetOrderItemSnapshot:
    @pytest.mark.asyncio
    async def test_item_includes_product_id_brand_and_image(self):
        """주문 상세의 items[] 에 product_id/브랜드/이미지 스냅샷이 포함된다."""
        order = _make_order()
        service = _make_service(order)

        result = await service.get_order(order.order_number)

        item = result.items[0]
        assert item.product_id == 18
        assert item.product_brand_snapshot == "LG전자"
        assert item.product_model_name_snapshot == "F21VDAP"
        assert item.product_image_url_snapshot == (
            "http://localhost:8333/rekle-images/products/1.jpg"
        )

    @pytest.mark.asyncio
    async def test_item_allows_null_brand_model_name_and_image(self):
        """브랜드/모델명/이미지가 없는 상품 스냅샷도 None 으로 정상 매핑된다."""
        order = _make_order()
        order.items[0].product_brand_snapshot = None
        order.items[0].product_model_name_snapshot = None
        order.items[0].product_image_url_snapshot = None
        service = _make_service(order)

        result = await service.get_order(order.order_number)

        item = result.items[0]
        assert item.product_brand_snapshot is None
        assert item.product_model_name_snapshot is None
        assert item.product_image_url_snapshot is None

    @pytest.mark.asyncio
    async def test_get_order_not_found(self):
        """존재하지 않는 주문번호 조회 시 OrderNotFoundError."""
        service = _make_service(None)

        with pytest.raises(OrderNotFoundError):
            await service.get_order("RK-0000000000")
