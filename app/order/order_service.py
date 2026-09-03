"""order 모듈 Service — 주문 생성/조회/취소 비즈니스 로직.

흐름 요약:
  get_quote      → 주소/상품 확인 → 배송비 계산 → QuoteResponse
  create_order   → 본인인증 → 주소/상품/재고 확인 → Order 저장 → OrderResponse
  list_orders    → 사용자 주문 목록 → OrderListResponse
  get_order      → 소유권 확인 → OrderResponse
  cancel_order   → 취소 가능 상태 확인 → CANCELLED 전환 → OrderResponse
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.address.models import Address
from app.catalog.models import ProductStatus
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
from app.core.pagination import build_page_meta
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
    ShipmentResponse,
)
from app.order.shipment import ShipmentMethod
from app.payment.payment_service import PaymentService

# PENDING / PAID / PREPARING 상태만 취소 허용
_CANCELLABLE_STATUSES = {OrderStatus.PENDING, OrderStatus.PAID, OrderStatus.PREPARING}

# 결제가 이미 이뤄진 상태 — 주문 취소 시 PG 환불도 함께 호출해야 한다
_PAID_STATUSES = {OrderStatus.PAID, OrderStatus.PREPARING}

# 결제 미완료 PENDING 주문 유효 시간 (지연 평가 방식)
_PAYMENT_TIMEOUT = timedelta(minutes=30)


class OrderService:
    def __init__(
        self, repo: OrderRepository, payment_service: PaymentService | None = None
    ) -> None:
        self._repo = repo
        # None 이면 PG 취소를 건너뛴다 (PG 상호작용을 검증하지 않는 단위 테스트용).
        # 운영 와이어링(deps.get_order_service)은 항상 주입한다.
        self._payment_service = payment_service

    # ── 견적 ────────────────────────────────────────────────────────

    async def get_quote(self, user_id: int, req: QuoteRequest) -> QuoteResponse:
        """배송비 포함 견적을 계산해 반환한다. 재고 락 없이 read-only 조회."""
        address = await self._get_address_for_user(user_id, req.address_id)

        direct_available = is_direct_delivery_available(address.zipcode)

        if req.shipping_method == ShipmentMethod.DIRECT and not direct_available:
            # DIRECT 불가 지역에서 DIRECT 선택 → OrderCancelForbiddenError 재활용
            # (별도 DirectDeliveryUnavailable 예외가 없으므로 기존 예외 사용)
            raise OrderCancelForbiddenError("직배송 불가 지역입니다.")

        shipping_fee, discount_amount = calc_shipping(req.shipping_method)

        items_total = 0
        for item_req in req.items:
            product = await self._repo.get_product(item_req.product_id)
            if product is None or product.status != ProductStatus.ACTIVE:
                raise ProductUnavailableError()
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
        """주문을 생성하고 재고를 차감한 뒤 OrderResponse 를 반환한다.

        identity_verified: 휴대폰 인증(Octomo) 완료 사용자만 통과 — 회원가입
        1차 인증과 첫 주문 전 확인이 이제 이 하나의 인증으로 통합돼 있다
        (`User.verified` = `phone_verified_at is not None`).
        """
        if not identity_verified:
            raise IdentityRequiredError()

        address = await self._get_address_for_user(user_id, req.address_id)

        if req.shipping_method == ShipmentMethod.DIRECT and not is_direct_delivery_available(
            address.zipcode
        ):
            raise OrderCancelForbiddenError("직배송 불가 지역입니다.")

        product_ids = [i.product_id for i in req.items]
        product_map = await self._repo.get_products_with_lock(product_ids)
        for item_req in req.items:
            product = product_map.get(item_req.product_id)
            if product is None or product.status != ProductStatus.ACTIVE:
                raise ProductUnavailableError()
            if product.stock < item_req.quantity:
                raise OutOfStockError()

        shipping_fee, discount_amount = calc_shipping(req.shipping_method)

        items_total = sum(
            product_map[i.product_id].price * i.quantity for i in req.items
        )
        total_amount = items_total + shipping_fee - discount_amount

        # order_number 임시값 — flush 후 PK 기반으로 교체
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

        order.items = [
            OrderItem(
                product_id=(p := product_map[i.product_id]).id,
                product_title_snapshot=p.title,
                product_brand_snapshot=p.brand,
                product_model_name_snapshot=p.model_name,
                product_image_url_snapshot=p.images[0].url if p.images else None,
                price_snapshot=p.price,
                quantity=i.quantity,
            )
            for i in req.items
        ]

        await self._repo.save(order)

        await self._repo.update_order_number(order, build_order_number(order.id))

        for item_req in req.items:
            await self._repo.decrement_stock(item_req.product_id, item_req.quantity)

        return _to_order_response(order)

    # ── 목록 ────────────────────────────────────────────────────────

    async def list_orders(
        self, user_id: int, page: int, size: int
    ) -> OrderListResponse:
        """사용자 주문 목록 (최신순, 페이지네이션)."""
        orders, total = await self._repo.get_list_by_user(user_id, page, size)
        return OrderListResponse(
            items=[_to_order_response(o) for o in orders],
            meta=build_page_meta(total, page, size),
        )

    # ── 단건 조회 ────────────────────────────────────────────────────

    async def get_order(self, user_id: int, order_number: str) -> OrderResponse:
        """order_number 로 단건 조회. 소유권 불일치는 OrderNotFoundError 로 처리(정보 노출 방지)."""
        order = await self._get_order_for_user(user_id, order_number)
        await self._expire_if_abandoned(order)
        return _to_order_response(order)

    # ── 배송 조회 ────────────────────────────────────────────────────

    async def get_shipment(self, user_id: int, order_number: str) -> ShipmentResponse:
        """order_number 의 배송 정보 반환. 소유권 불일치 및 배송 정보 미존재는 각각 404."""
        order = await self._repo.get_by_order_number_with_shipment(order_number)
        if order is None or order.user_id != user_id:
            raise OrderNotFoundError()
        if order.shipment is None:
            raise ShipmentNotFoundError()
        return ShipmentResponse.model_validate(order.shipment)

    # ── 환불 요청 ────────────────────────────────────────────────────

    async def request_refund(self, user_id: int, order_number: str) -> OrderResponse:
        """DELIVERED 상태 주문에 대해 환불을 요청한다.

        PG 전액 환불을 호출한 뒤 REFUNDED 로 전환한다. PG 가 거절하면 예외가 전파돼
        상태 전환은 일어나지 않는다. 배송 완료된 실물의 재고는 복구하지 않는다.
        """
        order = await self._get_order_for_user(user_id, order_number)

        if order.status != OrderStatus.DELIVERED:
            raise RefundForbiddenError()

        if self._payment_service is not None:
            await self._payment_service.cancel_payment(order.id, reason="구매자 환불 요청")

        order.status = OrderStatus.REFUNDED
        order.cancelled_at = datetime.now(UTC)

        return _to_order_response(order)

    # ── 취소 ────────────────────────────────────────────────────────

    async def cancel_order(self, user_id: int, order_number: str) -> OrderResponse:
        """PENDING/PAID/PREPARING 상태 주문을 취소한다.

        결제가 이뤄진 상태(PAID/PREPARING)면 PG 전액 취소를 먼저 호출한다 —
        PG 가 거절하면 예외가 전파돼 취소 자체가 롤백된다. PENDING(결제 전)은
        PG 호출 없이 상태만 전환한다.
        더블클릭/자동 재시도로 인한 동시 취소를 막기 위해 SELECT FOR UPDATE 를 사용한다.
        """
        order = await self._repo.get_by_order_number_with_lock(order_number)
        if order is None or order.user_id != user_id:
            raise OrderNotFoundError()

        if order.status not in _CANCELLABLE_STATUSES:
            raise OrderCancelForbiddenError()

        if order.status in _PAID_STATUSES and self._payment_service is not None:
            await self._payment_service.cancel_payment(order.id, reason="구매자 주문 취소")

        for item in order.items:
            await self._repo.increment_stock(item.product_id, item.quantity)

        order.status = OrderStatus.CANCELLED
        order.cancelled_at = datetime.now(UTC)

        return _to_order_response(order)

    # ── 내부 헬퍼 ────────────────────────────────────────────────────

    async def _get_address_for_user(self, user_id: int, address_id: int) -> Address:
        """배송지 존재(404) → 소유권(403) 순서로 검증 후 Address 반환."""
        address = await self._repo.get_address_by_id(address_id)
        if address is None:
            raise AddressNotFoundError()
        if address.user_id != user_id:
            raise PermissionDeniedError()
        return address

    async def _expire_if_abandoned(self, order: Order) -> None:
        """결제 기한(30분)이 지난 PENDING 주문을 즉시 취소하고 재고를 복구한다.

        지연 평가 방식 — 조회 시점에 만료 여부를 확인한다.
        2단계 확인: 1차 락 없이 후보 판단, 후보이면 FOR UPDATE 재조회 후 더블체크
        (동시 폴링으로 인한 재고 이중 복구 방지).
        """
        if order.status != OrderStatus.PENDING:
            return
        if datetime.now(UTC) - order.created_at < _PAYMENT_TIMEOUT:
            return
        # 2단계: 락을 잡고 상태 재확인 (다른 트랜잭션이 이미 처리했을 수 있음)
        locked_order = await self._repo.get_by_order_number_with_lock(order.order_number)
        if locked_order is None or locked_order.status != OrderStatus.PENDING:
            return
        for item in locked_order.items:
            await self._repo.increment_stock(item.product_id, item.quantity)
        locked_order.status = OrderStatus.CANCELLED
        locked_order.cancelled_at = datetime.now(UTC)

    async def _get_order_for_user(self, user_id: int, order_number: str) -> Order:
        """order_number 로 주문 조회 + 소유권 검증. 실패 시 OrderNotFoundError."""
        order = await self._repo.get_by_order_number(order_number)
        if order is None or order.user_id != user_id:
            raise OrderNotFoundError()
        return order


# ── 변환 헬퍼 ────────────────────────────────────────────────────────


def _to_order_item_response(item: OrderItem) -> OrderItemResponse:
    return OrderItemResponse(
        id=item.id if item.id is not None else 0,
        product_id=item.product_id,
        product_title_snapshot=item.product_title_snapshot,
        product_brand_snapshot=item.product_brand_snapshot,
        product_model_name_snapshot=item.product_model_name_snapshot,
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
