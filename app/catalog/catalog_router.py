"""catalog 모듈 Router — 상품·카테고리 HTTP 엔드포인트.

prefix '/products', '/categories' — /api/v1 상위 prefix 는 main.py 가 붙임.

주의: GET /products/featured 는 반드시 GET /products/{product_id} 보다 먼저 선언.
      FastAPI 는 동일 prefix 내에서 정적 경로를 파라미터 경로보다 먼저 매칭하지만,
      명시적 순서가 혼란을 방지한다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.catalog.catalog_schemas import (
    BulkProductRequest,
    CategoryMetaItem,
    ProductDetailResponse,
    ProductListParams,
    ProductListResponse,
    ProductResponse,
)
from app.catalog.catalog_service import CatalogService
from app.core.deps import get_catalog_service

router = APIRouter(tags=["catalog"])


@router.post(
    "/products/bulk",
    response_model=list[ProductResponse],
    status_code=status.HTTP_200_OK,
    summary="상품 ID 배열 bulk 조회",
)
async def get_products_bulk(
    body: BulkProductRequest,
    service: CatalogService = Depends(get_catalog_service),
) -> list[ProductResponse]:
    return await service.get_products_by_ids(body.ids)


@router.get(
    "/products/featured",
    response_model=list[ProductResponse],
    status_code=status.HTTP_200_OK,
    summary="홈 '오늘 입고된 상품' (최신 4건)",
)
async def get_featured(
    limit: int = Query(default=4, ge=1, le=20),
    service: CatalogService = Depends(get_catalog_service),
) -> list[ProductResponse]:
    return await service.get_featured(limit)


@router.get(
    "/products/{product_id}",
    response_model=ProductDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="상품 상세 (이미지·스펙 포함)",
)
async def get_product(
    product_id: int = Path(description="상품 PK"),
    service: CatalogService = Depends(get_catalog_service),
) -> ProductDetailResponse:
    """상품 상세 조회. 없으면 404 PRODUCT_NOT_FOUND."""
    return await service.get_product(product_id)


@router.get(
    "/products",
    response_model=ProductListResponse,
    status_code=status.HTTP_200_OK,
    summary="상품 목록 (필터·정렬·페이지네이션)",
)
async def list_products(
    params: Annotated[ProductListParams, Depends()],
    service: CatalogService = Depends(get_catalog_service),
) -> ProductListResponse:
    """ACTIVE 상품 목록.

    Query params:
    - category: REFRIGERATOR | WASHING_MACHINE | TV | AIR_CONDITIONER | KITCHEN | ETC
    - grade: A | B | C
    - min_price / max_price: 가격 범위 (원)
    - warranty: true 면 동작보증 상품만
    - q: 제목·브랜드·모델명 키워드 검색
    - sort: latest(기본) | price_asc | price_desc
    - page / size: 페이지네이션 (size 최대 100)
    """
    return await service.list_products(params)


@router.get(
    "/categories",
    response_model=list[CategoryMetaItem],
    status_code=status.HTTP_200_OK,
    summary="카테고리 목록 (정적)",
)
async def get_categories(
    service: CatalogService = Depends(get_catalog_service),
) -> list[CategoryMetaItem]:
    """프론트 홈 그리드·필터 칩용 카테고리 메타.
    DB 쿼리 없는 정적 응답 — 변경 시 배포 없이 캐시 무효화 가능.
    """
    return await service.get_categories()
