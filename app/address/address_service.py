"""address 모듈 Service — 배송지 CRUD + 기본 배송지 단일 보장."""

from __future__ import annotations

from app.address.address_repository import AddressRepository
from app.address.address_schemas import AddressCreate, AddressUpdate
from app.address.models import Address
from app.core.exceptions import AddressLimitExceeded, AddressNotFound

MAX_ADDRESSES_PER_USER = 10


class AddressService:
    def __init__(self, repo: AddressRepository) -> None:
        self._repo = repo

    async def list_addresses(self, user_id: int) -> list[Address]:
        return await self._repo.get_all_by_user_id(user_id)

    async def create_address(self, user_id: int, data: AddressCreate) -> Address:
        count = await self._repo.count_by_user_id(user_id)
        if count >= MAX_ADDRESSES_PER_USER:
            raise AddressLimitExceeded()
        if data.is_default:
            await self._repo.clear_default(user_id)
        address = Address(
            user_id=user_id,
            recipient=data.recipient,
            phone=data.phone,
            zipcode=data.zipcode,
            address1=data.address1,
            address2=data.address2,
            is_default=data.is_default,
        )
        return await self._repo.save(address)

    async def update_address(
        self, user_id: int, address_id: int, data: AddressUpdate
    ) -> Address:
        address = await self._repo.get_by_user_and_id(user_id, address_id)
        if address is None:
            raise AddressNotFound()
        update_fields = data.model_dump(exclude_unset=True)
        if update_fields.get("is_default"):
            await self._repo.clear_default(user_id)
        for key, value in update_fields.items():
            setattr(address, key, value)
        return address

    async def delete_address(self, user_id: int, address_id: int) -> None:
        address = await self._repo.get_by_user_and_id(user_id, address_id)
        if address is None:
            raise AddressNotFound()
        await self._repo.delete(address)
