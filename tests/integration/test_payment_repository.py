"""payment_repository 통합 테스트 — 실제 Postgres 대상.

increment_stock 은 원자적 SQL UPDATE 라 fake repo 로는 정확성을 검증할 수 없다.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import ConditionGrade, Product, ProductStatus
from app.payment.payment_repository import PaymentRepository


async def _make_product(
    session: AsyncSession, *, stock: int, status: ProductStatus = ProductStatus.SOLD_OUT
) -> Product:
    product = Product(
        title="결제통합테스트 상품",
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
async def test_increment_stock_from_sold_out_auto_restores_active(
    db_session: AsyncSession,
):
    """결제 실패/취소 웹훅으로 SOLD_OUT 상품 재고가 회복되면 ACTIVE 로 자동 복원된다."""
    product = await _make_product(db_session, stock=0, status=ProductStatus.SOLD_OUT)
    repo = PaymentRepository(db_session)

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
    repo = PaymentRepository(db_session)

    await repo.increment_stock(product.id, 1)
    await db_session.refresh(product)

    assert product.stock == 1
    assert product.status == ProductStatus.INACTIVE
