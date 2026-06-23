"""관리자 카테고리 CRUD 라우터."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, status

from app.catalog.admin_catalog_schemas import (
    AdminCategoryCreate,
    AdminCategoryResponse,
    AdminCategoryUpdate,
)
from app.catalog.admin_catalog_service import AdminCatalogService
from app.core.deps import get_admin_catalog_service, get_admin_user
from app.user.models import User

router = APIRouter(prefix="/admin/categories", tags=["admin-categories"])


@router.get(
    "",
    response_model=list[AdminCategoryResponse],
    status_code=status.HTTP_200_OK,
    summary="카테고리 목록 (관리자)",
)
async def list_categories(
    _: User = Depends(get_admin_user),
    service: AdminCatalogService = Depends(get_admin_catalog_service),
) -> list[AdminCategoryResponse]:
    return await service.list_categories()


@router.post(
    "",
    response_model=AdminCategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="카테고리 등록",
)
async def create_category(
    body: AdminCategoryCreate,
    _: User = Depends(get_admin_user),
    service: AdminCatalogService = Depends(get_admin_catalog_service),
) -> AdminCategoryResponse:
    """Errors: CATEGORY_ALREADY_EXISTS (409)"""
    return await service.create_category(body)


@router.patch(
    "/{category_id}",
    response_model=AdminCategoryResponse,
    status_code=status.HTTP_200_OK,
    summary="카테고리 수정",
)
async def update_category(
    body: AdminCategoryUpdate,
    category_id: str = Path(description="카테고리 ID (예: REFRIGERATOR)"),
    _: User = Depends(get_admin_user),
    service: AdminCatalogService = Depends(get_admin_catalog_service),
) -> AdminCategoryResponse:
    """Errors: CATEGORY_NOT_FOUND (404)"""
    return await service.update_category(category_id, body)


@router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="카테고리 삭제",
)
async def delete_category(
    category_id: str = Path(description="카테고리 ID"),
    _: User = Depends(get_admin_user),
    service: AdminCatalogService = Depends(get_admin_catalog_service),
) -> None:
    """Errors: CATEGORY_NOT_FOUND (404)"""
    await service.delete_category(category_id)
