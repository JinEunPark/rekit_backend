"""FastAPI Depends() 공용 의존성.

JPA 비유: Spring 의 @Autowired 가 채워주던 EntityManager / 서비스 빈을
여기 함수로 정의해서 라우터에서 `Depends(...)` 로 주입한다.

  - db_session: AsyncSession (= EntityManager)
  - get_payment_gateway, get_otp_sender 등은 외부 통합 어댑터 와이어링 자리

서비스/리포지토리 인스턴스 자체도 여기서 주입하면 테스트 시 fake 어댑터로
손쉽게 교체할 수 있다.
"""

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.auth_repository import AuthRepository
from app.auth.auth_service import AuthService
from app.core.database import async_session_factory


async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """단일 요청 스코프 트랜잭션 세션. 에러 시 자동 rollback."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# ── 도메인 서비스 팩토리 ─────────────────────────────────
# router 는 Depends(get_<도메인>_service) 로 service 를 받는다. 테스트에서는
# app.dependency_overrides[get_auth_service] = lambda: FakeService() 로 교체 가능.
# 다른 도메인도 같은 패턴으로 여기에 함수 한 개씩 추가.


async def get_auth_service(
    session: AsyncSession = Depends(db_session),
) -> AuthService:
    """AuthService 팩토리. session → Repository → Service 로 합성."""
    return AuthService(AuthRepository(session))
