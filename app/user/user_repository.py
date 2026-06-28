"""user 모듈 Repository — 탈퇴 시 소셜 계정 PII 정리."""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import SocialAccount


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def delete_social_accounts(self, user_id: int) -> None:
        """탈퇴 시 소셜 계정 행 삭제 — email_at_link 등 PII 즉시 파기."""
        await self.session.execute(
            delete(SocialAccount).where(SocialAccount.user_id == user_id)
        )
