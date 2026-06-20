"""address 모듈 Repository — DB 접근 캡슐화."""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.address.models import Address


class AddressRepository:
    """배송지 DB 접근 객체. 모든 쿼리는 여기 모은다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_all_by_user_id(self, user_id: int) -> list[Address]:
        """사용자의 전체 배송지 목록. 기본 배송지 먼저, id 오름차순 정렬."""
        result = await self._session.execute(
            select(Address)
            .where(Address.user_id == user_id)
            .order_by(Address.is_default.desc(), Address.id.asc())
        )
        return list(result.scalars().all())

    async def get_by_user_and_id(self, user_id: int, address_id: int) -> Address | None:
        result = await self._session.execute(
            select(Address).where(
                Address.user_id == user_id,
                Address.id == address_id,
            )
        )
        return result.scalar_one_or_none()

    async def count_by_user_id(self, user_id: int) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Address).where(Address.user_id == user_id)
        )
        return result.scalar_one()

    async def clear_default(self, user_id: int) -> None:
        """사용자의 모든 기본 배송지 플래그를 False 로 일괄 해제."""
        await self._session.execute(
            update(Address)
            .where(Address.user_id == user_id, Address.is_default.is_(True))
            .values(is_default=False)
        )

    async def save(self, address: Address) -> Address:
        self._session.add(address)
        await self._session.flush()
        await self._session.refresh(address)
        return address

    async def delete(self, address: Address) -> None:
        await self._session.delete(address)
        await self._session.flush()
