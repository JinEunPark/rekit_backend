"""admin_order_repository 통합 테스트 — FOR UPDATE 락 실제 동작 확인.

fake repo 단위 테스트로는 "실제로 두 번째 트랜잭션이 대기하는지"를 검증할 수
없다 — 이 동시성 자체가 검증 대상이므로 실제 Postgres 두 커넥션으로 확인한다.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import ConditionGrade, Product, ProductStatus
from app.core.database import async_session_factory
from app.order.admin_order_repository import AdminOrderRepository
from app.order.models import Order, OrderStatus
from app.order.shipment import ShipmentMethod
from app.user.models import User


async def _make_product(
    session: AsyncSession, *, stock: int, status: ProductStatus = ProductStatus.SOLD_OUT
) -> Product:
    product = Product(
        title="관리자통합테스트 상품",
        category="ETC",
        condition_grade=ConditionGrade.B,
        price=10_000,
        stock=stock,
        status=status,
    )
    session.add(product)
    await session.flush()
    return product


async def _make_order(session: AsyncSession, *, order_number: str) -> Order:
    user = (await session.execute(select(User).limit(1))).scalars().first()
    assert user is not None, "테스트 대상 DB에 최소 1명의 User 가 있어야 함"
    order = Order(
        order_number=order_number,
        user_id=user.id,
        total_amount=10_000,
        shipping_fee=0,
        discount_amount=0,
        shipping_method=ShipmentMethod.PARCEL,
        status=OrderStatus.PENDING,
        recipient_name="락테스트",
        recipient_phone="01000000000",
        zipcode="00000",
        address1="락테스트 주소",
    )
    session.add(order)
    await session.flush()
    return order


@pytest.mark.asyncio
async def test_get_order_for_update_actually_locks_the_row(db_session: AsyncSession):
    """첫 트랜잭션이 FOR UPDATE로 잠근 행을 두 번째 트랜잭션은 즉시 읽지 못하고 대기한다."""
    order_number = "RK-LOCKTEST0001"
    order = await _make_order(db_session, order_number=order_number)
    order_id = order.id
    await db_session.commit()  # 다른 세션(커넥션)에서 보이게 하려면 커밋 필요

    try:
        async with async_session_factory() as session_a:
            repo_a = AdminOrderRepository(session_a)
            locked = await repo_a.get_order_for_update(order_number)
            assert locked is not None

            async def _try_lock_from_second_session() -> None:
                async with async_session_factory() as session_b:
                    repo_b = AdminOrderRepository(session_b)
                    await repo_b.get_order_for_update(order_number)

            with pytest.raises(TimeoutError):
                await asyncio.wait_for(_try_lock_from_second_session(), timeout=1.0)

            await session_a.rollback()
    finally:
        async with async_session_factory() as cleanup_session:
            await cleanup_session.execute(delete(Order).where(Order.id == order_id))
            await cleanup_session.commit()


@pytest.mark.asyncio
async def test_increment_stock_from_sold_out_auto_restores_active(
    db_session: AsyncSession,
):
    """관리자 주문 취소로 SOLD_OUT 상품 재고가 회복되면 ACTIVE 로 자동 복원된다."""
    product = await _make_product(db_session, stock=0, status=ProductStatus.SOLD_OUT)
    repo = AdminOrderRepository(db_session)

    await repo.increment_stock(product.id, 1)
    await db_session.refresh(product)

    assert product.stock == 1
    assert product.status == ProductStatus.ACTIVE


@pytest.mark.asyncio
async def test_increment_stock_does_not_reactivate_inactive_product(
    db_session: AsyncSession,
):
    """운영자가 수동으로 INACTIVE 처리한 상품은 재고가 회복돼도 자동 활성화되지 않는다."""
    product = await _make_product(db_session, stock=0, status=ProductStatus.INACTIVE)
    repo = AdminOrderRepository(db_session)

    await repo.increment_stock(product.id, 1)
    await db_session.refresh(product)

    assert product.stock == 1
    assert product.status == ProductStatus.INACTIVE
