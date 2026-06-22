"""관리자 상품 CRUD 서비스."""

from __future__ import annotations

from app.catalog.admin_catalog_schemas import (
    AdminProductCreate,
    AdminProductDetailResponse,
    AdminProductImageResponse,
    AdminProductImagesReplace,
    AdminProductListParams,
    AdminProductListResponse,
    AdminProductUpdate,
)
from app.catalog.catalog_repository import CatalogRepository
from app.catalog.catalog_utils import discount_pct as _discount_pct
from app.catalog.models import Product, ProductImage, ProductStatus
from app.core.exceptions import ProductNotFound
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
            raise ProductNotFound()
        return _to_detail(product)

    async def update_product(
        self, product_id: int, data: AdminProductUpdate
    ) -> AdminProductDetailResponse:
        product = await self._repo.get_by_id(product_id)
        if product is None:
            raise ProductNotFound()
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(product, key, value)
        return _to_detail(product)

    async def replace_images(
        self, product_id: int, data: AdminProductImagesReplace
    ) -> AdminProductDetailResponse:
        product = await self._repo.get_by_id(product_id)
        if product is None:
            raise ProductNotFound()
        await self._repo.replace_images(product, data.images)
        return _to_detail(product)

    async def delete_product(self, product_id: int) -> None:
        product = await self._repo.get_by_id(product_id)
        if product is None:
            raise ProductNotFound()
        product.status = ProductStatus.INACTIVE


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
