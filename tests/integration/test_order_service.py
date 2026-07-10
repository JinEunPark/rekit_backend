"""OrderService 통합 테스트 — 실제 Postgres 대상 동시성 검증.

단위 테스트(fake repo)로는 "실제로 두 번째 트랜잭션이 대기하는지"를 검증할 수
없다 — FOR UPDATE 락이 실제로 동시 취소를 막는지 Postgres 두 커넥션으로 확인한다.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import ConditionGrade, Product, ProductStatus
from app.core.database import async_session_factory
from app.core.exceptions import OrderCancelForbiddenError
from app.order.models import Order, OrderItem, OrderStatus
from app.order.order_repository import OrderRepository
from app.order.order_service import OrderService
from app.order.shipment import ShipmentMethod
from app.user.models import User

# ── 픽스처 헬퍼 ─────────────────────────────────────────────────────────


async def _get_or_create_user(session: AsyncSession) -> User:
    user = (await session.execute(select(User).limit(1))).scalars().first()
    assert user is not None, "테스트 대상 DB에 최소 1명의 User 가 있어야 함"
    return user


async def _make_product(session: AsyncSession, *, stock: int) -> Product:
    product = Product(
        title="동시성테스트 상품",
        category="ETC",
        condition_grade=ConditionGrade.B,
        price=10_000,
        stock=stock,
        status=ProductStatus.ACTIVE,
    )
    session.add(product)
    await session.flush()
    return product


async def _make_pending_order(
    session: AsyncSession,
    *,
    order_number: str,
    user_id: int,
    product_id: int,
    quantity: int,
) -> Order:
    """PENDING 주문(아이템 포함)을 생성한다."""
    order = Order(
        order_number=order_number,
        user_id=user_id,
        total_amount=10_000 * quantity,
        shipping_fee=5_000,
        discount_amount=0,
        shipping_method=ShipmentMethod.PARCEL,
        status=OrderStatus.PENDING,
        recipient_name="동시성테스트",
        recipient_phone="01000000000",
        zipcode="00000",
        address1="테스트 주소",
    )
    order.items = [
        OrderItem(
            product_id=product_id,
            product_title_snapshot="동시성테스트 상품",
            price_snapshot=10_000,
            quantity=quantity,
        )
    ]
    session.add(order)
    await session.flush()
    return order


# ── 동시성 테스트 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_order_concurrent_double_click_only_restores_stock_once(
    db_session: AsyncSession,
) -> None:
    """더블클릭 시나리오: 동시에 두 번 취소 시도해도 재고가 1회분만 복구된다.

    Given: 재고 5인 상품 1개로 만든 PENDING 주문(quantity=2)
    When:  asyncio.gather 로 동일 order_number 에 cancel_order 를 거의 동시에 두 번 호출
    Then:  정확히 하나만 성공, 나머지는 OrderCancelForbiddenError(이미 CANCELLED)
           재고는 5+2=7 이 되어야 하고 5+2+2=9 가 되면 안 됨
    """
    # Arrange
    user = await _get_or_create_user(db_session)
    product = await _make_product(db_session, stock=5)
    order = await _make_pending_order(
        db_session,
        order_number="RK-CONCTEST0001",
        user_id=user.id,
        product_id=product.id,
        quantity=2,
    )
    product_id = product.id
    order_number = order.order_number
    user_id = user.id
    await db_session.commit()  # 다른 세션에서 보이게 커밋

    try:

        async def _cancel() -> bool:
            """새 세션에서 cancel_order 시도. 성공 시 True, 이미 취소됐으면 False."""
            async with async_session_factory() as session:
                repo = OrderRepository(session)
                service = OrderService(repo)
                try:
                    await service.cancel_order(
                        user_id=user_id, order_number=order_number
                    )
                    await session.commit()
                    return True
                except OrderCancelForbiddenError:
                    await session.rollback()
                    return False

        results = await asyncio.gather(
            _cancel(),
            _cancel(),
            return_exceptions=True,
        )

        # 두 결과 중 정확히 하나만 True(성공), 나머지는 False(이미 취소됨)
        successes = [r for r in results if r is True]
        assert len(successes) == 1, f"성공이 1번이어야 하는데 {successes}"

        # 재고 확인: 5(초기) + 2(1회 복구) = 7, 이중 복구 시 9가 됨
        async with async_session_factory() as verify_session:
            refreshed = (
                await verify_session.execute(
                    select(Product).where(Product.id == product_id)
                )
            ).scalar_one()
            assert refreshed.stock == 7, f"재고가 7이어야 하는데 {refreshed.stock}"

    finally:
        # 테스트 데이터 정리 (order items 는 cascade 로 삭제됨)
        async with async_session_factory() as cleanup:
            await cleanup.execute(
                delete(Order).where(Order.order_number == order_number)
            )
            await cleanup.execute(delete(Product).where(Product.id == product_id))
            await cleanup.commit()


@pytest.mark.asyncio
async def test_get_order_concurrent_abandonment_expires_stock_once(
    db_session: AsyncSession,
) -> None:
    """동시 폴링 시나리오: 30분 경과 PENDING 주문을 동시에 두 번 get_order해도
    재고가 정확히 1회만 복구된다.

    Given: 재고 5인 상품 + 30분 초과 PENDING 주문(quantity=2)
    When:  asyncio.gather 로 동일 order_number 에 get_order 를 동시에 두 번 호출
    Then:  재고는 5+2=7 (1회 복구), 이중 복구 시 9 가 되면 안 됨
    """
    # Arrange
    user = await _get_or_create_user(db_session)
    product = await _make_product(db_session, stock=5)
    order = await _make_pending_order(
        db_session,
        order_number="RK-CONCTEST0002",
        user_id=user.id,
        product_id=product.id,
        quantity=2,
    )
    product_id = product.id
    order_number = order.order_number
    user_id = user.id
    order_id = order.id
    await db_session.flush()

    # created_at 을 35분 전으로 back-date (server_default 를 직접 UPDATE)
    expired_at = datetime.now(UTC) - timedelta(minutes=35)
    await db_session.execute(
        update(Order)
        .where(Order.id == order_id)
        .values(created_at=expired_at)
    )
    await db_session.commit()  # 다른 세션에서 보이게 커밋

    try:

        async def _get() -> None:
            """새 세션에서 get_order 호출."""
            async with async_session_factory() as session:
                repo = OrderRepository(session)
                service = OrderService(repo)
                await service.get_order(user_id=user_id, order_number=order_number)
                await session.commit()

        await asyncio.gather(_get(), _get(), return_exceptions=True)

        # 재고 확인: 5(초기) + 2(1회 복구) = 7
        async with async_session_factory() as verify_session:
            refreshed = (
                await verify_session.execute(
                    select(Product).where(Product.id == product_id)
                )
            ).scalar_one()
            assert refreshed.stock == 7, f"재고가 7이어야 하는데 {refreshed.stock}"

    finally:
        async with async_session_factory() as cleanup:
            await cleanup.execute(
                delete(Order).where(Order.order_number == order_number)
            )
            await cleanup.execute(delete(Product).where(Product.id == product_id))
            await cleanup.commit()
