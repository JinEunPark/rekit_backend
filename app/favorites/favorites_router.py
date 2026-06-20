from fastapi import APIRouter, Depends, Path, status

from app.core.deps import get_active_user, get_favorites_service
from app.favorites.favorites_schemas import FavoriteProductItem, FavoriteToggleResponse
from app.favorites.favorites_service import FavoritesService
from app.user.models import User

router = APIRouter(prefix="/favorites", tags=["favorites"])


@router.get(
    "",
    response_model=list[FavoriteProductItem],
    status_code=status.HTTP_200_OK,
    summary="관심상품 목록",
)
async def list_favorites(
    user: User = Depends(get_active_user),
    service: FavoritesService = Depends(get_favorites_service),
) -> list[FavoriteProductItem]:
    return await service.list_favorites(user.id)


@router.post(
    "/{product_id}",
    response_model=FavoriteToggleResponse,
    status_code=status.HTTP_200_OK,
    summary="관심상품 추가 (멱등)",
)
async def add_favorite(
    product_id: int = Path(description="상품 PK"),
    user: User = Depends(get_active_user),
    service: FavoritesService = Depends(get_favorites_service),
) -> FavoriteToggleResponse:
    return await service.add_favorite(user.id, product_id)


@router.delete(
    "/{product_id}",
    response_model=FavoriteToggleResponse,
    status_code=status.HTTP_200_OK,
    summary="관심상품 제거",
)
async def remove_favorite(
    product_id: int = Path(description="상품 PK"),
    user: User = Depends(get_active_user),
    service: FavoritesService = Depends(get_favorites_service),
) -> FavoriteToggleResponse:
    """Errors: FAVORITE_NOT_FOUND (404)"""
    return await service.remove_favorite(user.id, product_id)
