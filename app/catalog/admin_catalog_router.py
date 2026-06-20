"""관리자 상품 CRUD 라우터."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from app.catalog.admin_catalog_schemas import (
    AdminProductCreate,
    AdminProductDetailResponse,
    AdminProductListParams,
    AdminProductListResponse,
    AdminProductUpdate,
)
from app.catalog.admin_catalog_service import AdminCatalogService
from app.core.deps import get_admin_catalog_service, get_admin_user
from app.user.models import User

router = APIRouter(prefix="/admin/products", tags=["admin-products"])


@router.get(
    "",
    response_model=AdminProductListResponse,
    status_code=status.HTTP_200_OK,
    summary="관리자 상품 목록 (전체 status)",
)
async def list_products(
    params: Annotated[AdminProductListParams, Depends()],
    _: User = Depends(get_admin_user),
    service: AdminCatalogService = Depends(get_admin_catalog_service),
) -> AdminProductListResponse:
    return await service.list_products(params)


@router.post(
    "",
    response_model=AdminProductDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="상품 등록",
)
async def create_product(
    body: AdminProductCreate,
    _: User = Depends(get_admin_user),
    service: AdminCatalogService = Depends(get_admin_catalog_service),
) -> AdminProductDetailResponse:
    return await service.create_product(body)


@router.get(
    "/{product_id}",
    response_model=AdminProductDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="상품 상세 조회 (관리자)",
)
async def get_product(
    product_id: int = Path(description="상품 PK"),
    _: User = Depends(get_admin_user),
    service: AdminCatalogService = Depends(get_admin_catalog_service),
) -> AdminProductDetailResponse:
    return await service.get_product(product_id)


@router.patch(
    "/{product_id}",
    response_model=AdminProductDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="상품 수정",
)
async def update_product(
    body: AdminProductUpdate,
    product_id: int = Path(description="상품 PK"),
    _: User = Depends(get_admin_user),
    service: AdminCatalogService = Depends(get_admin_catalog_service),
) -> AdminProductDetailResponse:
    return await service.update_product(product_id, body)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="상품 소프트 삭제 (INACTIVE 전환)",
)
async def delete_product(
    product_id: int = Path(description="상품 PK"),
    _: User = Depends(get_admin_user),
    service: AdminCatalogService = Depends(get_admin_catalog_service),
) -> None:
    await service.delete_product(product_id)
