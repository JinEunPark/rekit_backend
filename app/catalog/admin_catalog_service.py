"""관리자 상품 CRUD 서비스."""

from __future__ import annotations

from app.catalog.admin_catalog_schemas import (
    AdminCategoryCreate,
    AdminCategoryResponse,
    AdminCategoryUpdate,
    AdminProductCreate,
    AdminProductDetailResponse,
    AdminProductImageResponse,
    AdminProductImagesReplace,
    AdminProductImageUpdate,
    AdminProductListParams,
    AdminProductListResponse,
    AdminProductUpdate,
)
from app.catalog.catalog_repository import CatalogRepository
from app.catalog.catalog_utils import discount_pct as _discount_pct
from app.catalog.models import Product, ProductCategoryMetaItem, ProductImage, ProductStatus
from app.core.exceptions import (
    CategoryAlreadyExistsError,
    CategoryNotFoundError,
    ProductImageNotFoundError,
    ProductNotFoundError,
)
from app.core.pagination import build_page_meta


class AdminCatalogService:
    def __init__(self, repo: CatalogRepository) -> None:
        self._repo = repo

    async def list_products(
        self, params: AdminProductListParams
    ) -> AdminProductListResponse:
        products, total = await self._repo.admin_get_list(params)
        return AdminProductListResponse(
            items=[_to_detail(p) for p in products],
            meta=build_page_meta(total, params.page, params.size),
        )

    async def create_product(
        self, data: AdminProductCreate
    ) -> AdminProductDetailResponse:
        product = Product(
            title=data.title,
            description=data.description,
            category=data.category,
            brand=data.brand,
            model_name=data.model_name,
            year_estimate=data.year_estimate,
            condition_grade=data.condition_grade,
            warranty_works=data.warranty_works,
            price=data.price,
            original_price=data.original_price,
            weight_kg=data.weight_kg,
            width_cm=data.width_cm,
            depth_cm=data.depth_cm,
            height_cm=data.height_cm,
            stock=data.stock,
            status=data.status,
        )
        for i, url in enumerate(data.image_urls):
            product.images.append(ProductImage(url=url, sort_order=i))
        await self._repo.save(product)
        return _to_detail(product)

    async def get_product(self, product_id: int) -> AdminProductDetailResponse:
        product = await self._repo.get_by_id(product_id)
        if product is None:
            raise ProductNotFoundError()
        return _to_detail(product)

    async def update_product(
        self, product_id: int, data: AdminProductUpdate
    ) -> AdminProductDetailResponse:
        product = await self._repo.get_by_id(product_id)
        if product is None:
            raise ProductNotFoundError()
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(product, key, value)
        return _to_detail(product)

    async def replace_images(
        self, product_id: int, data: AdminProductImagesReplace
    ) -> AdminProductDetailResponse:
        product = await self._repo.get_by_id(product_id)
        if product is None:
            raise ProductNotFoundError()
        images = [
            ProductImage(product_id=product.id, url=item.url, sort_order=i, label=item.label)
            for i, item in enumerate(data.images)
        ]
        await self._repo.replace_images(product, images)
        return _to_detail(product)

    async def update_image(
        self, product_id: int, image_id: int, data: AdminProductImageUpdate
    ) -> AdminProductDetailResponse:
        product = await self._repo.get_by_id(product_id)
        if product is None:
            raise ProductNotFoundError()
        image = next((img for img in product.images if img.id == image_id), None)
        if image is None:
            raise ProductImageNotFoundError()
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(image, key, value)
        return _to_detail(product)

    async def delete_product(self, product_id: int) -> None:
        product = await self._repo.get_by_id(product_id)
        if product is None:
            raise ProductNotFoundError()
        product.status = ProductStatus.INACTIVE

    # ── 카테고리 CRUD ──────────────────────────────────────────

    async def list_categories(self) -> list[AdminCategoryResponse]:
        cats = await self._repo.get_categories()
        return [AdminCategoryResponse.model_validate(c) for c in cats]

    async def create_category(self, data: AdminCategoryCreate) -> AdminCategoryResponse:
        existing = await self._repo.get_category_by_id(data.id)
        if existing is not None:
            raise CategoryAlreadyExistsError()
        cat = ProductCategoryMetaItem(
            id=data.id, title=data.title, icon=data.icon, sort_order=data.sort_order
        )
        await self._repo.save_category(cat)
        return AdminCategoryResponse.model_validate(cat)

    async def update_category(
        self, category_id: str, data: AdminCategoryUpdate
    ) -> AdminCategoryResponse:
        cat = await self._repo.get_category_by_id(category_id)
        if cat is None:
            raise CategoryNotFoundError()
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(cat, key, value)
        return AdminCategoryResponse.model_validate(cat)

    async def delete_category(self, category_id: str) -> None:
        cat = await self._repo.get_category_by_id(category_id)
        if cat is None:
            raise CategoryNotFoundError()
        await self._repo.delete_category(cat)


def _to_image(img: ProductImage) -> AdminProductImageResponse:
    return AdminProductImageResponse(
        id=img.id,
        url=img.url,
        sort_order=img.sort_order,
        label=img.label,
    )


def _to_detail(product: Product) -> AdminProductDetailResponse:
    return AdminProductDetailResponse(
        id=product.id,
        title=product.title,
        description=product.description,
        category=product.category,
        brand=product.brand,
        model_name=product.model_name,
        year_estimate=product.year_estimate,
        condition_grade=product.condition_grade,
        warranty_works=product.warranty_works,
        price=product.price,
        original_price=product.original_price,
        discount_pct=_discount_pct(product),
        weight_kg=product.weight_kg,
        width_cm=product.width_cm,
        depth_cm=product.depth_cm,
        height_cm=product.height_cm,
        stock=product.stock,
        status=product.status,
        images=[_to_image(img) for img in product.images],
        created_at=product.created_at,
    )
