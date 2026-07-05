"""order 모듈 Repository 통합 테스트 — 실제 Postgres 대상.

increment_stock/decrement_stock 은 원자적 SQL UPDATE 라 fake repo 로는
정확성을 검증할 수 없다.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import ConditionGrade, Product, ProductStatus
from app.order.order_repository import OrderRepository


async def _make_product(session: AsyncSession, *, stock: int) -> Product:
    product = Product(
        title="통합테스트 상품",
        category="ETC",
        condition_grade=ConditionGrade.B,
        price=10_000,
        stock=stock,
        status=ProductStatus.ACTIVE,
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
