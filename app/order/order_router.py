"""order 모듈 Router — 주문 관련 엔드포인트.

엔드포인트:
  POST /orders/quote                견적 조회 (로그인 필요)
  POST /orders                      주문 생성 → 201
  GET  /orders                      내 주문 목록
  GET  /orders/{order_number}       주문 단건 조회
  POST /orders/{order_number}/cancel 주문 취소
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import get_active_user, get_order_service
from app.order.order_schemas import (
    CreateOrderRequest,
    OrderListResponse,
    OrderResponse,
    QuoteRequest,
    QuoteResponse,
    ShipmentResponse,
)
from app.order.order_service import OrderService
from app.user.models import User

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/quote", response_model=QuoteResponse)
async def get_quote(
    body: QuoteRequest,
    user: User = Depends(get_active_user),
    service: OrderService = Depends(get_order_service),
) -> QuoteResponse:
    """배송비 포함 견적을 반환한다. 실제 주문 전 금액 확인용."""
    return await service.get_quote(user_id=user.id, req=body)


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    body: CreateOrderRequest,
    user: User = Depends(get_active_user),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    """주문을 생성하고 재고를 차감한다. 본인인증이 완료된 사용자만 가능."""
    return await service.create_order(
        user_id=user.id,
        req=body,
        identity_verified=user.verified,
    )


@router.get("", response_model=OrderListResponse)
async def list_orders(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_active_user),
    service: OrderService = Depends(get_order_service),
) -> OrderListResponse:
    """내 주문 목록 (최신순, 페이지네이션)."""
    return await service.list_orders(user_id=user.id, page=page, size=size)


@router.get("/{order_number}", response_model=OrderResponse)
async def get_order(
    order_number: str,
    user: User = Depends(get_active_user),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    """주문 단건 조회. 타인의 주문은 404 반환(정보 노출 방지)."""
    return await service.get_order(user_id=user.id, order_number=order_number)


@router.post("/{order_number}/cancel", response_model=OrderResponse)
async def cancel_order(
    order_number: str,
    user: User = Depends(get_active_user),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    """PENDING/PAID/PREPARING 상태 주문을 취소한다."""
    return await service.cancel_order(user_id=user.id, order_number=order_number)


@router.get("/{order_number}/shipment", response_model=ShipmentResponse)
async def get_shipment(
    order_number: str,
    user: User = Depends(get_active_user),
    service: OrderService = Depends(get_order_service),
) -> ShipmentResponse:
    """주문의 배송 정보를 조회한다. 배송 정보가 없으면 404."""
    return await service.get_shipment(user_id=user.id, order_number=order_number)


@router.post("/{order_number}/refund/request", response_model=OrderResponse)
async def request_refund(
    order_number: str,
    user: User = Depends(get_active_user),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    """DELIVERED 상태 주문에 환불을 요청한다 (MVP: PG 취소 없이 상태만 변경)."""
    return await service.request_refund(user_id=user.id, order_number=order_number)
