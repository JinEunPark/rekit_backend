"""address 모듈 Router — /addresses prefix.

api.md §5 배송지 API:
- GET    /addresses          : 목록 조회
- POST   /addresses          : 배송지 추가
- PATCH  /addresses/{id}     : 배송지 수정 (기본 배송지 설정 포함)
- DELETE /addresses/{id}     : 배송지 삭제
"""

from fastapi import APIRouter, Depends, status

from app.address.address_schemas import AddressCreate, AddressResponse, AddressUpdate
from app.address.address_service import AddressService
from app.core.deps import get_active_user, get_address_service
from app.user.models import User

router = APIRouter(prefix="/addresses", tags=["addresses"])


@router.get(
    "",
    response_model=list[AddressResponse],
    response_model_by_alias=True,
    status_code=status.HTTP_200_OK,
    summary="배송지 목록 조회",
)
async def list_addresses(
    user: User = Depends(get_active_user),
    service: AddressService = Depends(get_address_service),
) -> list[AddressResponse]:
    """로그인 사용자의 배송지 전체 목록. 기본 배송지가 맨 앞에 정렬된다."""
    addresses = await service.list_addresses(user.id)
    return [AddressResponse.model_validate(a) for a in addresses]


@router.post(
    "",
    response_model=AddressResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="배송지 추가",
)
async def create_address(
    body: AddressCreate,
    user: User = Depends(get_active_user),
    service: AddressService = Depends(get_address_service),
) -> AddressResponse:
    """새 배송지 등록. isDefault=true 이면 기존 기본 배송지가 해제된다. 최대 10개.

    Errors:
    - ADDRESS_LIMIT_EXCEEDED (422): 10개 초과
    """
    address = await service.create_address(user.id, body)
    return AddressResponse.model_validate(address)


@router.patch(
    "/{address_id}",
    response_model=AddressResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_200_OK,
    summary="배송지 수정",
)
async def update_address(
    address_id: int,
    body: AddressUpdate,
    user: User = Depends(get_active_user),
    service: AddressService = Depends(get_address_service),
) -> AddressResponse:
    """배송지 수정. 보내지 않은 필드는 유지된다. isDefault=true 로 기본 배송지 설정 가능.

    Errors:
    - ADDRESS_NOT_FOUND (404): 본인 배송지가 아니거나 존재하지 않음
    """
    address = await service.update_address(user.id, address_id, body)
    return AddressResponse.model_validate(address)


@router.delete(
    "/{address_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="배송지 삭제",
)
async def delete_address(
    address_id: int,
    user: User = Depends(get_active_user),
    service: AddressService = Depends(get_address_service),
) -> None:
    """배송지 삭제. 기본 배송지 삭제 시 다른 배송지가 자동으로 기본이 되지 않는다.

    Errors:
    - ADDRESS_NOT_FOUND (404): 본인 배송지가 아니거나 존재하지 않음
    """
    await service.delete_address(user.id, address_id)
