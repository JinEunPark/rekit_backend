"""order 모듈 Repository 통합 테스트 — 실제 Postgres 대상.

increment_stock/decrement_stock 은 원자적 SQL UPDATE 라 fake repo 로는
정확성을 검증할 수 없다.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import ConditionGrade, Product, ProductStatus
from app.order.order_repository import OrderRepository


async def _make_product(
    session: AsyncSession, *, stock: int, status: ProductStatus = ProductStatus.ACTIVE
) -> Product:
    product = Product(
        title="통합테스트 상품",
        category="ETC",
        condition_grade=ConditionGrade.B,
        price=10_000,
        stock=stock,
        status=status,
    )
    session.add(product)
    await session.flush()
    return product


@pytest.mark.asyncio
async def test_increment_stock_adds_quantity(db_session: AsyncSession):
    """재고 5 인 상품에 +2 하면 7 이 된다."""
    product = await _make_product(db_session, stock=5)
    repo = OrderRepository(db_session)

    await repo.increment_stock(product.id, 2)
    await db_session.refresh(product)

    assert product.stock == 7


@pytest.mark.asyncio
async def test_increment_stock_and_decrement_stock_are_symmetric(db_session: AsyncSession):
    """감산 후 동일 수량 가산하면 원래 재고로 돌아온다."""
    product = await _make_product(db_session, stock=10)
    repo = OrderRepository(db_session)

    await repo.decrement_stock(product.id, 3)
    await repo.increment_stock(product.id, 3)
    await db_session.refresh(product)

    assert product.stock == 10


@pytest.mark.asyncio
async def test_decrement_stock_to_zero_auto_transitions_to_sold_out(
    db_session: AsyncSession,
):
    """재고가 0 이 되면 ACTIVE → SOLD_OUT 으로 자동 전환된다."""
    product = await _make_product(db_session, stock=1)
    repo = OrderRepository(db_session)

    await repo.decrement_stock(product.id, 1)
    await db_session.refresh(product)

    assert product.stock == 0
    assert product.status == ProductStatus.SOLD_OUT


@pytest.mark.asyncio
async def test_decrement_stock_above_zero_keeps_active(db_session: AsyncSession):
    """재고가 남아있으면 ACTIVE 상태를 유지한다."""
    product = await _make_product(db_session, stock=5)
    repo = OrderRepository(db_session)

    await repo.decrement_stock(product.id, 2)
    await db_session.refresh(product)

    assert product.stock == 3
    assert product.status == ProductStatus.ACTIVE


@pytest.mark.asyncio
async def test_increment_stock_from_sold_out_auto_restores_active(
    db_session: AsyncSession,
):
    """SOLD_OUT 상품의 재고가 회복되면 ACTIVE 로 자동 복원된다."""
    product = await _make_product(db_session, stock=0, status=ProductStatus.SOLD_OUT)
    repo = OrderRepository(db_session)

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
    repo = OrderRepository(db_session)

    await repo.increment_stock(product.id, 1)
    await db_session.refresh(product)

    assert product.stock == 1
    assert product.status == ProductStatus.INACTIVE
