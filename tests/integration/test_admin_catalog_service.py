"""admin_catalog_service 통합 테스트 — stock 변경 시 FOR UPDATE 락 실제 동작 확인.

fake repo 단위 테스트로는 "실제로 두 번째 트랜잭션이 대기하는지"를 검증할 수
없다 — 이 동시성 자체가 검증 대상이므로 실제 Postgres 두 커넥션으로 확인한다.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.admin_catalog_schemas import AdminProductUpdate
from app.catalog.admin_catalog_service import AdminCatalogService
from app.catalog.catalog_repository import CatalogRepository
from app.catalog.models import ConditionGrade, Product, ProductStatus
from app.core.database import async_session_factory


async def _make_product(session: AsyncSession, *, stock: int) -> Product:
    product = Product(
        title="통합테스트 상품 (락)",
        category="ETC",
        condition_grade=ConditionGrade.B,
        price=10_000,
        stock=stock,
        status=ProductStatus.ACTIVE,
    )
    session.add(product)
    await session.flush()
    await session.commit()
    await session.refresh(product)
    return product


@pytest.mark.asyncio
async def test_update_product_stock_change_blocks_until_other_transaction_releases(
    db_session: AsyncSession,
) -> None:
    """첫 트랜잭션이 FOR UPDATE로 잠근 Product를 stock 변경 PATCH는 대기한다."""
    product = await _make_product(db_session, stock=10)
    product_id = product.id

    try:
        async with async_session_factory() as session_a:
            # 첫 트랜잭션: Product를 FOR UPDATE로 잠금
            repo_a = CatalogRepository(session_a)
            locked = await repo_a.get_by_id_with_lock(product_id)
            assert locked is not None

            async def _update_stock_from_second_session() -> None:
                async with async_session_factory() as session_b:
                    repo_b = CatalogRepository(session_b)
                    service_b = AdminCatalogService(repo_b)  # type: ignore[arg-type]
                    await service_b.update_product(product_id, AdminProductUpdate(stock=100))

            # 두 번째 세션의 stock 변경은 첫 트랜잭션이 잠겨있는 동안 블록됨
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(_update_stock_from_second_session(), timeout=1.0)

            await session_a.rollback()
    finally:
        async with async_session_factory() as cleanup:
            await cleanup.execute(delete(Product).where(Product.id == product_id))
            await cleanup.commit()
