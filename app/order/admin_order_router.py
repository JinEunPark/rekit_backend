"""관리자 주문 Router."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.deps import get_admin_order_service, get_admin_user
from app.order.admin_order_schemas import (
    AdminOrderCancelRequest,
    AdminOrderDetail,
    AdminOrderListParams,
    AdminOrderListResponse,
    AdminOrderStatusUpdate,
    AdminShipmentInput,
)
from app.order.admin_order_service import AdminOrderService
from app.user.models import User

router = APIRouter(prefix="/admin/orders", tags=["admin-orders"])


@router.get("/export.csv", summary="주문 CSV 내보내기")
async def export_csv(
    _: User = Depends(get_admin_user),
    service: AdminOrderService = Depends(get_admin_order_service),
) -> StreamingResponse:
    content = await service.export_csv()
    return StreamingResponse(
        iter([content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders.csv"},
    )


@router.get("", response_model=AdminOrderListResponse, summary="주문 목록 (상태탭 카운트 포함)")
async def list_orders(
    params: Annotated[AdminOrderListParams, Depends()],
    _: User = Depends(get_admin_user),
    service: AdminOrderService = Depends(get_admin_order_service),
) -> AdminOrderListResponse:
    return await service.list_orders(params)


@router.get("/{order_number}", response_model=AdminOrderDetail, summary="주문 상세")
async def get_order(
    order_number: str,
    _: User = Depends(get_admin_user),
    service: AdminOrderService = Depends(get_admin_order_service),
) -> AdminOrderDetail:
    return await service.get_order(order_number)


@router.post(
    "/{order_number}/shipment",
    response_model=AdminOrderDetail,
    summary="송장 입력 → SHIPPING 전환",
)
async def input_shipment(
    order_number: str,
    body: AdminShipmentInput,
    _: User = Depends(get_admin_user),
    service: AdminOrderService = Depends(get_admin_order_service),
) -> AdminOrderDetail:
    return await service.input_shipment(order_number, body)


@router.patch(
    "/{order_number}/status",
    response_model=AdminOrderDetail,
    summary="주문 상태 수동 변경",
)
async def update_status(
    order_number: str,
    body: AdminOrderStatusUpdate,
    _: User = Depends(get_admin_user),
    service: AdminOrderService = Depends(get_admin_order_service),
) -> AdminOrderDetail:
    return await service.update_status(order_number, body)


@router.post(
    "/{order_number}/cancel",
    response_model=AdminOrderDetail,
    summary="관리자 주문 취소",
)
async def cancel_order(
    order_number: str,
    body: AdminOrderCancelRequest,
    _: User = Depends(get_admin_user),
    service: AdminOrderService = Depends(get_admin_order_service),
) -> AdminOrderDetail:
    return await service.cancel_order(order_number, body)
