"""관리자 주문 서비스."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from app.core.exceptions import InvalidOrderStatus, OrderCancelForbidden, OrderNotFound
from app.core.pagination import build_page_meta
from app.order.admin_order_repository import AdminOrderRepository
from app.order.admin_order_schemas import (
    AdminOrderCancelRequest,
    AdminOrderDetail,
    AdminOrderItemSummary,
    AdminOrderListItem,
    AdminOrderListParams,
    AdminOrderListResponse,
    AdminOrderStatusCounts,
    AdminOrderStatusUpdate,
    AdminShipmentInfo,
    AdminShipmentInput,
)
from app.order.models import Order, OrderStatus
from app.payment.models import PaymentStatus

_CANCELLABLE = {OrderStatus.PENDING, OrderStatus.PAID, OrderStatus.PREPARING}
_MANUAL_SETTABLE = {OrderStatus.PREPARING, OrderStatus.SHIPPING, OrderStatus.DELIVERED}


class AdminOrderService:
    def __init__(self, repo: AdminOrderRepository) -> None:
        self._repo = repo

    async def list_orders(self, params: AdminOrderListParams) -> AdminOrderListResponse:
        orders, total = await self._repo.get_list(params)
        raw = await self._repo.status_counts()
        counts = AdminOrderStatusCounts(
            all=sum(raw.values()),
            paid=raw.get("PAID", 0),
            preparing=raw.get("PREPARING", 0),
            shipping=raw.get("SHIPPING", 0),
            delivered=raw.get("DELIVERED", 0),
            cancelled=raw.get("CANCELLED", 0) + raw.get("REFUNDED", 0),
        )
        return AdminOrderListResponse(
            items=[_to_list_item(o) for o in orders],
            counts=counts,
            meta=build_page_meta(total, params.page, params.size),
        )

    async def get_order(self, order_number: str) -> AdminOrderDetail:
        order = await self._repo.get_by_order_number(order_number)
        if order is None:
            raise OrderNotFound()
        return _to_detail(order)

    async def input_shipment(
        self, order_number: str, body: AdminShipmentInput
    ) -> AdminOrderDetail:
        order = await self._repo.get_order_for_update(order_number)
        if order is None:
            raise OrderNotFound()
        if order.status not in {OrderStatus.PAID, OrderStatus.PREPARING}:
            raise InvalidOrderStatus("송장은 결제완료/준비중 상태에서만 입력 가능합니다.")
        await self._repo.create_or_update_shipment(order, body.carrier, body.tracking_number)
        order.status = OrderStatus.SHIPPING
        return await self.get_order(order_number)

    async def update_status(
        self, order_number: str, body: AdminOrderStatusUpdate
    ) -> AdminOrderDetail:
        order = await self._repo.get_order_for_update(order_number)
        if order is None:
            raise OrderNotFound()
        if body.status not in _MANUAL_SETTABLE:
            raise InvalidOrderStatus(
                f"수동 변경 가능 상태: {[s.value for s in _MANUAL_SETTABLE]}"
            )
        order.status = body.status
        return await self.get_order(order_number)

    async def cancel_order(
        self, order_number: str, body: AdminOrderCancelRequest
    ) -> AdminOrderDetail:
        order = await self._repo.get_order_for_update(order_number)
        if order is None:
            raise OrderNotFound()
        if order.status not in _CANCELLABLE:
            raise OrderCancelForbidden()
        order.status = OrderStatus.CANCELLED
        order.cancelled_at = datetime.now(UTC)
        return await self.get_order(order_number)

    async def export_csv(self) -> str:
        orders, _ = await self._repo.get_list(AdminOrderListParams(size=10000))
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["주문번호", "주문일시", "주문자", "연락처", "상품", "금액", "상태", "배송방식"])
        for o in orders:
            title = o.items[0].product_title_snapshot if o.items else ""
            writer.writerow([
                o.order_number,
                o.created_at.strftime("%Y-%m-%d %H:%M"),
                o.user.username,
                o.recipient_phone,
                title,
                o.total_amount,
                o.status.value,
                o.shipping_method.value,
            ])
        return buf.getvalue()


def _to_list_item(order: Order) -> AdminOrderListItem:
    return AdminOrderListItem(
        order_number=order.order_number,
        created_at=order.created_at,
        username=order.user.username,
        recipient_phone=order.recipient_phone,
        item_count=len(order.items),
        first_item_title=order.items[0].product_title_snapshot if order.items else "",
        total_amount=order.total_amount,
        status=order.status,
        shipping_method=order.shipping_method,
    )


def _to_detail(order: Order) -> AdminOrderDetail:
    paid = next((p for p in order.payments if p.status == PaymentStatus.PAID), None)
    return AdminOrderDetail(
        order_number=order.order_number,
        created_at=order.created_at,
        status=order.status,
        shipping_method=order.shipping_method,
        total_amount=order.total_amount,
        shipping_fee=order.shipping_fee,
        discount_amount=order.discount_amount,
        memo=order.memo,
        user_id=order.user.id,
        username=order.user.username,
        email=order.user.email,
        recipient_name=order.recipient_name,
        recipient_phone=order.recipient_phone,
        zipcode=order.zipcode,
        address1=order.address1,
        address2=order.address2,
        items=[
            AdminOrderItemSummary(
                product_title_snapshot=i.product_title_snapshot,
                quantity=i.quantity,
                price_snapshot=i.price_snapshot,
            )
            for i in order.items
        ],
        payment_method=paid.method.value if paid else None,
        paid_at=order.paid_at,
        cancelled_at=order.cancelled_at,
        shipment=AdminShipmentInfo.model_validate(order.shipment) if order.shipment else None,
    )
