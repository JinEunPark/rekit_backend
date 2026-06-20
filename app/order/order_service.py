"""order 모듈 Service — 주문 생성/조회/취소 비즈니스 로직.

흐름 요약:
  get_quote      → 주소/상품 확인 → 배송비 계산 → QuoteResponse
  create_order   → 본인인증 → 주소/상품/재고 확인 → Order 저장 → OrderResponse
  list_orders    → 사용자 주문 목록 → OrderListResponse
  get_order      → 소유권 확인 → OrderResponse
  cancel_order   → 취소 가능 상태 확인 → CANCELLED 전환 → OrderResponse
"""

from __future__ import annotations

from datetime import UTC, datetime
from math import ceil

from app.catalog.models import ProductStatus
from app.core.exceptions import (
    AddressNotFound,
    IdentityRequired,
    OrderCancelForbidden,
    OrderNotFound,
    OutOfStock,
)
from app.core.pagination import PageMeta
from app.core.shipping import calc_shipping, is_direct_delivery_available
from app.order.models import Order, OrderItem, OrderStatus
from app.order.order_number import build_order_number
from app.order.order_repository import OrderRepository
from app.order.order_schemas import (
    CreateOrderRequest,
    OrderItemResponse,
    OrderListResponse,
    OrderResponse,
    QuoteRequest,
    QuoteResponse,
)
from app.order.shipment import ShipmentMethod

# PENDING / PAID / PREPARING 상태만 취소 허용
_CANCELLABLE_STATUSES = {OrderStatus.PENDING, OrderStatus.PAID, OrderStatus.PREPARING}


class OrderService:
    def __init__(self, repo: OrderRepository) -> None:
        self._repo = repo

    # ── 견적 ────────────────────────────────────────────────────────

    async def get_quote(self, user_id: int, req: QuoteRequest) -> QuoteResponse:
        """배송비 포함 견적을 계산해 반환한다. 재고 락 없이 read-only 조회."""
        address = await self._repo.get_address_by_user(user_id, req.address_id)
        if address is None:
            raise AddressNotFound()

        direct_available = is_direct_delivery_available(address.zipcode)

        if req.shipping_method == ShipmentMethod.DIRECT and not direct_available:
            # DIRECT 불가 지역에서 DIRECT 선택 → OrderCancelForbidden 재활용
            # (별도 DirectDeliveryUnavailable 예외가 없으므로 기존 예외 사용)
            raise OrderCancelForbidden("직배송 불가 지역입니다.")

        shipping_fee, discount_amount = calc_shipping(req.shipping_method)

        items_total = 0
        for item_req in req.items:
            product = await self._repo.get_product_with_lock(item_req.product_id)
            if product is None or product.status != ProductStatus.ACTIVE:
                raise OutOfStock()
            items_total += product.price * item_req.quantity

        total_amount = items_total + shipping_fee - discount_amount

        return QuoteResponse(
            items_total=items_total,
            shipping_fee=shipping_fee,
            discount_amount=discount_amount,
            total_amount=total_amount,
            shipping_method=req.shipping_method,
            direct_available=direct_available,
        )

    # ── 주문 생성 ────────────────────────────────────────────────────

    async def create_order(
        self,
        user_id: int,
        req: CreateOrderRequest,
        identity_verified: bool,
    ) -> OrderResponse:
        """주문을 생성하고 재고를 차감한 뒤 OrderResponse 를 반환한다."""
        # 1. 본인인증 확인
        if not identity_verified:
            raise IdentityRequired()

        # 2. 배송지 확인 + 소유권
        address = await self._repo.get_address_by_user(user_id, req.address_id)
        if address is None:
            raise AddressNotFound()

        # 3. DIRECT 배송 가능 지역 확인
        if req.shipping_method == ShipmentMethod.DIRECT:
            if not is_direct_delivery_available(address.zipcode):
                raise OrderCancelForbidden("직배송 불가 지역입니다.")

        # 4. 상품 확인 + 재고 확인 (FOR UPDATE 락)
        product_map = {}
        for item_req in req.items:
            product = await self._repo.get_product_with_lock(item_req.product_id)
            if product is None or product.status != ProductStatus.ACTIVE:
                raise OutOfStock()
            if product.stock < item_req.quantity:
                raise OutOfStock()
            product_map[item_req.product_id] = product

        # 5. 배송비 계산
        shipping_fee, discount_amount = calc_shipping(req.shipping_method)

        items_total = sum(
            product_map[i.product_id].price * i.quantity for i in req.items
        )
        total_amount = items_total + shipping_fee - discount_amount

        # 6. Order 생성 (order_number 임시값 — flush 후 PK 기반으로 교체)
        order = Order(
            order_number="RK-PENDING",
            user_id=user_id,
            total_amount=total_amount,
            shipping_fee=shipping_fee,
            discount_amount=discount_amount,
            shipping_method=req.shipping_method,
            status=OrderStatus.PENDING,
            recipient_name=address.recipient,
            recipient_phone=address.phone,
            zipcode=address.zipcode,
            address1=address.address1,
            address2=address.address2,
            memo=req.memo,
        )

        # 7. OrderItem 생성 (스냅샷)
        order_items: list[OrderItem] = []
        for item_req in req.items:
            product = product_map[item_req.product_id]
            image_url = product.images[0].url if product.images else None
            order_items.append(
                OrderItem(
                    product_id=product.id,
                    product_title_snapshot=product.title,
                    product_image_url_snapshot=image_url,
                    price_snapshot=product.price,
                    quantity=item_req.quantity,
                )
            )
        order.items = order_items

        # 8. flush → order.id 확보
        await self._repo.save(order)

        # 9. PK 기반 order_number 생성 후 교체
        order_number = build_order_number(order.id)
        await self._repo.update_order_number(order, order_number)

        # 10. 재고 차감
        for item_req in req.items:
            await self._repo.decrement_stock(item_req.product_id, item_req.quantity)

        # 11. 응답 반환
        return _to_order_response(order)

    # ── 목록 ────────────────────────────────────────────────────────

    async def list_orders(
        self, user_id: int, page: int, size: int
    ) -> OrderListResponse:
        """사용자 주문 목록 (최신순, 페이지네이션)."""
        orders, total = await self._repo.get_list_by_user(user_id, page, size)
        total_pages = ceil(total / size) if total else 0
        return OrderListResponse(
            items=[_to_order_response(o) for o in orders],
            meta=PageMeta(page=page, size=size, total=total, total_pages=total_pages),
        )

    # ── 단건 조회 ────────────────────────────────────────────────────

    async def get_order(self, user_id: int, order_number: str) -> OrderResponse:
        """order_number 로 단건 조회. 소유권 불일치는 OrderNotFound 로 처리(정보 노출 방지)."""
        order = await self._repo.get_by_order_number(order_number)
        if order is None or order.user_id != user_id:
            raise OrderNotFound()
        return _to_order_response(order)

    # ── 취소 ────────────────────────────────────────────────────────

    async def cancel_order(self, user_id: int, order_number: str) -> OrderResponse:
        """PENDING/PAID/PREPARING 상태 주문을 취소한다.

        PAID 이상의 결제 취소(PG 호출)는 payment 모듈 책임이며, 여기서는 상태만 전환.
        """
        order = await self._repo.get_by_order_number(order_number)
        if order is None or order.user_id != user_id:
            raise OrderNotFound()

        if order.status not in _CANCELLABLE_STATUSES:
            raise OrderCancelForbidden()

        order.status = OrderStatus.CANCELLED
        order.cancelled_at = datetime.now(UTC)

        return _to_order_response(order)


# ── 변환 헬퍼 ────────────────────────────────────────────────────────


def _to_order_item_response(item: OrderItem) -> OrderItemResponse:
    return OrderItemResponse(
        id=item.id if item.id is not None else 0,
        product_id=item.product_id,
        product_title_snapshot=item.product_title_snapshot,
        product_image_url_snapshot=item.product_image_url_snapshot,
        price_snapshot=item.price_snapshot,
        quantity=item.quantity,
        subtotal=item.price_snapshot * item.quantity,
    )


def _to_order_response(order: Order) -> OrderResponse:
    return OrderResponse(
        id=order.id if order.id is not None else 0,
        order_number=order.order_number,
        status=order.status,
        total_amount=order.total_amount,
        shipping_fee=order.shipping_fee,
        discount_amount=order.discount_amount,
        shipping_method=order.shipping_method,
        recipient_name=order.recipient_name,
        recipient_phone=order.recipient_phone,
        address1=order.address1,
        address2=order.address2,
        memo=order.memo,
        items=[_to_order_item_response(i) for i in order.items],
        paid_at=order.paid_at,
        cancelled_at=order.cancelled_at,
        created_at=order.created_at,
    )
