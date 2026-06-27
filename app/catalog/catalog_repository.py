"""catalog 모듈 Repository — products / product_images 테이블 접근.

- service 만 호출. router 직접 호출 금지 (CLAUDE.md 모듈 규칙).
- 필터링/정렬/페이지네이션은 모두 SQL 레이어에서 처리 (Python 루프 금지).
- 이미지는 selectinload 로 N+1 방지.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.catalog.catalog_schemas import ProductListParams, ProductSort
from app.catalog.models import Product, ProductCategoryMetaItem, ProductImage, ProductStatus

if TYPE_CHECKING:
    from app.catalog.admin_catalog_schemas import AdminProductListParams


class CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_list(self, params: ProductListParams) -> tuple[list[Product], int]:
        """필터·정렬·페이지네이션 적용 후 (items, total) 반환.

        total 은 페이지네이션 적용 전 전체 매칭 건수 — 클라이언트 totalPages 계산용.
        이미지는 selectinload 로 한 번에 가져옴 (N+1 방지).
        """
        base = select(Product).where(Product.status == ProductStatus.ACTIVE)

        if params.category is not None:
            base = base.where(Product.category == params.category)
        if params.grade is not None:
            base = base.where(Product.condition_grade == params.grade)
        if params.min_price is not None:
            base = base.where(Product.price >= params.min_price)
        if params.max_price is not None:
            base = base.where(Product.price <= params.max_price)
        if params.warranty is not None:
            base = base.where(Product.warranty_works == params.warranty)
        if params.q:
            pattern = f"%{params.q}%"
            base = base.where(
                or_(
                    Product.title.ilike(pattern),
                    Product.brand.ilike(pattern),
                    Product.model_name.ilike(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total: int = (await self.session.execute(count_stmt)).scalar_one()

        if params.sort == ProductSort.PRICE_ASC:
            base = base.order_by(Product.price.asc(), Product.id.asc())
        elif params.sort == ProductSort.PRICE_DESC:
            base = base.order_by(Product.price.desc(), Product.id.asc())
        else:
            base = base.order_by(Product.created_at.desc(), Product.id.desc())

        base = (
            base.offset((params.page - 1) * params.size)
            .limit(params.size)
            .options(selectinload(Product.images.and_(ProductImage.sort_order == 0)))
        )

        result = await self.session.execute(base)
        return list(result.scalars()), total

    async def get_by_id(self, product_id: int) -> Product | None:
        """PK 로 상품 단건 조회 (이미지 포함). 없으면 None."""
        stmt = (
            select(Product)
            .where(Product.id == product_id)
            .options(selectinload(Product.images))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def admin_get_list(
        self, params: AdminProductListParams
    ) -> tuple[list[Product], int]:
        """관리자용 상품 목록 — 모든 status 포함, q/status 필터, 페이지네이션."""
        base = select(Product)
        if params.status is not None:
            base = base.where(Product.status == params.status)
        if params.q:
            pattern = f"%{params.q}%"
            base = base.where(
                or_(
                    Product.title.ilike(pattern),
                    Product.brand.ilike(pattern),
                    Product.model_name.ilike(pattern),
                )
            )
        count_stmt = select(func.count()).select_from(base.subquery())
        total: int = (await self.session.execute(count_stmt)).scalar_one()
        base = (
            base.order_by(Product.created_at.desc(), Product.id.desc())
            .offset((params.page - 1) * params.size)
            .limit(params.size)
            .options(selectinload(Product.images))
        )
        result = await self.session.execute(base)
        return list(result.scalars()), total

    async def save(self, product: Product) -> Product:
        """신규/기존 상품 저장 후 flush (PK 필요 시). images 즉시 로드."""
        self.session.add(product)
        await self.session.flush()
        await self.session.refresh(product, attribute_names=["images"])
        return product

    async def replace_images(
        self, product: Product, images: list[ProductImage]
    ) -> Product:
        """기존 이미지 전부 삭제 후 새 목록으로 원자적 교체.

        images 는 서비스가 미리 product_id·sort_order 를 채운 ProductImage 목록.
        """
        await self.session.execute(
            delete(ProductImage).where(ProductImage.product_id == product.id)
        )
        self.session.add_all(images)
        await self.session.flush()
        await self.session.refresh(product, attribute_names=["images"])
        return product

    async def get_by_ids(self, product_ids: list[int]) -> list[Product]:
        """ID 목록으로 상품 bulk 조회. 없는 ID 는 조용히 무시."""
        stmt = (
            select(Product)
            .where(Product.id.in_(product_ids))
            .options(selectinload(Product.images.and_(ProductImage.sort_order == 0)))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def get_featured(self, limit: int = 4) -> list[Product]:
        """홈 '오늘 입고된 상품' — ACTIVE 상품을 최신순으로 limit 건."""
        stmt = (
            select(Product)
            .where(Product.status == ProductStatus.ACTIVE)
            .order_by(Product.created_at.desc(), Product.id.desc())
            .limit(limit)
            .options(selectinload(Product.images.and_(ProductImage.sort_order == 0)))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def get_categories(self) -> list[ProductCategoryMetaItem]:
        stmt = select(ProductCategoryMetaItem).order_by(ProductCategoryMetaItem.sort_order)
        return list((await self.session.execute(stmt)).scalars())

    async def get_category_by_id(self, category_id: str) -> ProductCategoryMetaItem | None:
        return (
            await self.session.execute(
                select(ProductCategoryMetaItem).where(ProductCategoryMetaItem.id == category_id)
            )
        ).scalar_one_or_none()

    async def save_category(self, category: ProductCategoryMetaItem) -> ProductCategoryMetaItem:
        self.session.add(category)
        await self.session.flush()
        return category

    async def delete_category(self, category: ProductCategoryMetaItem) -> None:
        await self.session.delete(category)
        await self.session.flush()
