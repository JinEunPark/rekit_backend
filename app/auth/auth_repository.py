"""auth 모듈 Repository — User 테이블 접근 레이어.

JPA 비유: @Repository / Spring Data JPA Repository 인터페이스 + 구현.
- AsyncSession 을 생성자 주입 (= EntityManager 주입). 트랜잭션 경계는 호출자
  (router 의 db_session dependency) 가 관리한다.
- ORM 객체(User) 반환. DTO 변환은 service 가 담당.
- service 만 호출. router 가 직접 호출하면 안 됨 (CLAUDE.md 모듈 규칙).

다른 도메인 Repository 작성 시 같은 패턴 — 도메인별로 1개씩 두고, 같은 모듈의
service 만 의존시킨다. 모듈 간 cross-import 가 필요하면 string ref 또는 service
레이어에서 합성한다 (models.py 가 다른 모듈 model 을 import 하면 안 됨).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import SocialAccount, SocialProvider
from app.user.models import User


class AuthRepository:
    """auth 컨텍스트에서 User 를 조회/갱신하는 책임."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_login_id(self, login_id: str) -> User | None:
        """로그인 아이디로 단일 사용자 조회. 없으면 None.

        login_id 는 case-sensitive (User.login_id 컬럼이 그대로 매칭).
        """
        stmt = select(User).where(User.login_id == login_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        """PK 로 단일 사용자 조회. session.get 은 1차 캐시 활용 + WHERE id=? 한 번."""
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """이메일로 단일 사용자 조회. find-id / find-password 에서 사용.

        주의: email 은 호출 전에 lowercase 정규화돼 있어야 함 (service 책임).
        DB 의 unique 제약이 case-sensitive 라 정규화 안 하면 매칭 실패.
        """
        stmt = select(User).where(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_login_id_and_email(self, login_id: str, email: str) -> User | None:
        """loginId + email 둘 다 일치하는 단일 사용자 조회. find-password 에서 사용.

        한쪽만 알아도 임시 비번 발급되는 걸 막기 위해 둘 다 매칭. email 은 사전에
        lowercase 정규화돼 있어야 한다.
        """
        stmt = select(User).where(User.login_id == login_id, User.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def exists_by_login_id(self, login_id: str) -> bool:
        """로그인 아이디 중복 검사. 회원가입 / check-login-id 에서 사용.

        SELECT 1 ... LIMIT 1 패턴 — 행 전체를 가져오지 않아 가볍다.
        """
        stmt = select(User.id).where(User.login_id == login_id).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def exists_by_email(self, email: str) -> bool:
        """이메일 중복 검사. 회원가입에서 EMAIL_TAKEN 판정에 사용.

        주의: email 은 호출 전에 lowercase 정규화돼 있어야 함 (service 책임).
        """
        stmt = select(User.id).where(User.email == email).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def add(self, user: User) -> User:
        """User INSERT + flush 로 PK 채워서 반환.

        commit 은 호출자(db_session dependency) 가 응답 직전에 일괄 처리한다 —
        한 요청 = 한 트랜잭션 정책. flush 가 필요한 이유는 service 가 user.id 를
        토큰 claim 에 즉시 써야 하기 때문.
        refresh 는 호출하지 않음 — service 가 모든 컬럼을 명시 set 하고 응답이
        server_default 컬럼을 쓰지 않아서.
        """
        self.session.add(user)
        await self.session.flush()
        return user

    # ── 소셜 로그인 연결 ───────────────────────────────────

    async def get_social_account(
        self, provider: SocialProvider, social_id: str
    ) -> SocialAccount | None:
        """(provider, social_id) 매칭으로 연결된 SocialAccount 조회.

        매칭되는 row 가 있으면 — 이미 연결된 사용자. service 는 user 만 꺼내 로그인.
        """
        stmt = select(SocialAccount).where(
            SocialAccount.provider == provider,
            SocialAccount.social_id == social_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add_social_account(self, account: SocialAccount) -> SocialAccount:
        """SocialAccount INSERT + flush. user_id 가 이미 set 돼있어야 함."""
        self.session.add(account)
        await self.session.flush()
        return account
