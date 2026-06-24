"""address 서비스 단위 테스트 — Repository AsyncMock 사용.

DB 없이 서비스 로직(기본 배송지 단일 보장, 한도 초과 거부, 소유 확인 등)을 검증한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.address.address_schemas import AddressCreate, AddressUpdate
from app.address.address_service import MAX_ADDRESSES_PER_USER, AddressService
from app.address.models import Address
from app.core.exceptions import AddressLimitExceeded, AddressNotFound

# ── 테스트 헬퍼 ───────────────────────────────────────


def _make_repo(
    *,
    addresses: list[Address] | None = None,
    count: int = 0,
    found: Address | None = None,
) -> MagicMock:
    """AddressRepository mock. found 는 get_by_user_and_id 반환값."""
    repo = MagicMock()
    repo.get_all_by_user_id = AsyncMock(return_value=addresses or [])
    repo.get_by_user_and_id = AsyncMock(return_value=found)
    repo.count_by_user_id = AsyncMock(return_value=count)
    repo.clear_default = AsyncMock()
    repo.save = AsyncMock(side_effect=lambda a: a)
    repo.delete = AsyncMock()
    return repo


def _make_address(*, address_id: int = 1, is_default: bool = False) -> Address:
    addr = Address(
        user_id=1,
        recipient="홍길동",
        phone="01012345678",
        zipcode="12345",
        address1="서울시 강남구",
        is_default=is_default,
    )
    addr.id = address_id
    return addr


def _create_data(*, is_default: bool = False) -> AddressCreate:
    return AddressCreate(
        recipient="홍길동",
        phone="01012345678",
        zipcode="12345",
        address1="서울시 강남구",
        is_default=is_default,
    )


# ── list_addresses ────────────────────────────────────


class TestListAddresses:
    @pytest.mark.asyncio
    async def test_returns_all_addresses_from_repo(self) -> None:
        addrs = [_make_address(address_id=1), _make_address(address_id=2)]
        service = AddressService(_make_repo(addresses=addrs))

        result = await service.list_addresses(user_id=1)

        assert result == addrs

    @pytest.mark.asyncio
    async def test_empty_user_returns_empty_list(self) -> None:
        service = AddressService(_make_repo(addresses=[]))

        result = await service.list_addresses(user_id=1)

        assert result == []


# ── create_address ────────────────────────────────────


class TestCreateAddress:
    @pytest.mark.asyncio
    async def test_create_saves_address(self) -> None:
        service = AddressService(_make_repo(count=0))

        result = await service.create_address(1, _create_data())

        assert result.recipient == "홍길동"

    @pytest.mark.asyncio
    async def test_create_with_is_default_clears_existing(self) -> None:
        repo = _make_repo(count=1)
        service = AddressService(repo)

        await service.create_address(1, _create_data(is_default=True))

        repo.clear_default.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_create_without_is_default_skips_clear(self) -> None:
        repo = _make_repo(count=1)
        service = AddressService(repo)

        await service.create_address(1, _create_data(is_default=False))

        repo.clear_default.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_at_limit_raises_address_limit_exceeded(self) -> None:
        service = AddressService(_make_repo(count=MAX_ADDRESSES_PER_USER))

        with pytest.raises(AddressLimitExceeded):
            await service.create_address(1, _create_data())

    @pytest.mark.asyncio
    async def test_create_just_below_limit_succeeds(self) -> None:
        service = AddressService(_make_repo(count=MAX_ADDRESSES_PER_USER - 1))

        result = await service.create_address(1, _create_data())

        assert result is not None


# ── update_address ────────────────────────────────────


class TestUpdateAddress:
    @pytest.mark.asyncio
    async def test_update_not_found_raises_address_not_found(self) -> None:
        service = AddressService(_make_repo(found=None))

        with pytest.raises(AddressNotFound):
            await service.update_address(1, 99, AddressUpdate())

    @pytest.mark.asyncio
    async def test_update_partial_changes_only_given_fields(self) -> None:
        addr = _make_address()
        service = AddressService(_make_repo(found=addr))

        result = await service.update_address(1, 1, AddressUpdate(recipient="김철수"))

        assert result.recipient == "김철수"
        assert result.phone == "01012345678"  # 변경 안 됨

    @pytest.mark.asyncio
    async def test_update_set_is_default_true_clears_others(self) -> None:
        addr = _make_address()
        repo = _make_repo(found=addr)
        service = AddressService(repo)

        await service.update_address(1, 1, AddressUpdate(is_default=True))

        repo.clear_default.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_update_without_is_default_skips_clear(self) -> None:
        addr = _make_address()
        repo = _make_repo(found=addr)
        service = AddressService(repo)

        await service.update_address(1, 1, AddressUpdate(recipient="김철수"))

        repo.clear_default.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_is_default_false_does_not_clear(self) -> None:
        """is_default=False 명시는 이 배송지를 기본에서 해제할 뿐, 다른 것을 clear 안 함."""
        addr = _make_address(is_default=True)
        repo = _make_repo(found=addr)
        service = AddressService(repo)

        await service.update_address(1, 1, AddressUpdate(is_default=False))

        repo.clear_default.assert_not_called()
        assert addr.is_default is False


# ── delete_address ────────────────────────────────────


class TestDeleteAddress:
    @pytest.mark.asyncio
    async def test_delete_not_found_raises_address_not_found(self) -> None:
        service = AddressService(_make_repo(found=None))

        with pytest.raises(AddressNotFound):
            await service.delete_address(1, 99)

    @pytest.mark.asyncio
    async def test_delete_calls_repo_delete(self) -> None:
        addr = _make_address()
        repo = _make_repo(found=addr)
        service = AddressService(repo)

        await service.delete_address(1, 1)

        repo.delete.assert_called_once_with(addr)
