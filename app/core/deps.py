"""FastAPI Depends() 공용 의존성.

JPA 비유: Spring 의 @Autowired 가 채워주던 EntityManager / 서비스 빈을
여기 함수로 정의해서 라우터에서 `Depends(...)` 로 주입한다.

  - db_session: AsyncSession (= EntityManager)
  - get_email_sender: 외부 어댑터 (이메일 발송)
  - get_<domain>_service: 도메인 서비스 팩토리
  - get_current_user / get_active_user: 인증 가드

서비스/리포지토리 인스턴스 자체도 여기서 주입하면 테스트 시 fake 어댑터로
손쉽게 교체할 수 있다 (`app.dependency_overrides[...]`).
"""

from collections.abc import AsyncGenerator
from functools import lru_cache

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.address.address_repository import AddressRepository
from app.address.address_service import AddressService
from app.admin.dashboard_service import DashboardService
from app.admin.sales_service import SalesService
from app.auth.adapters.oauth_factory import build_oauth_provider
from app.auth.adapters.octomo import OctomoPhoneVerifier
from app.auth.adapters.ports import OAuthProvider
from app.auth.auth_repository import AuthRepository
from app.auth.auth_service import AuthService
from app.auth.models import SocialProvider
from app.cart.cart_repository import CartRepository
from app.cart.cart_service import CartService
from app.catalog.admin_catalog_service import AdminCatalogService
from app.catalog.catalog_repository import CatalogRepository
from app.catalog.catalog_service import CatalogService
from app.common.email import ConsoleEmailSender, EmailSender, GmailSmtpEmailSender
from app.core.config import Settings, settings
from app.core.database import async_session_factory
from app.core.exceptions import (
    AccountInactiveError,
    PasswordChangeRequiredError,
    PermissionDeniedError,
    TokenExpiredError,
)
from app.core.redis import get_redis
from app.core.security import decode_token
from app.favorites.favorites_repository import FavoritesRepository
from app.favorites.favorites_service import FavoritesService
from app.help.repository import HelpRepository
from app.help.service import AdminHelpService, HelpService
from app.order.admin_order_repository import AdminOrderRepository
from app.order.admin_order_service import AdminOrderService
from app.order.order_repository import OrderRepository
from app.order.order_service import OrderService
from app.payment.adapters.ports import PaymentGateway
from app.payment.payment_repository import PaymentRepository
from app.payment.payment_service import PaymentService
from app.user.admin_members_repository import AdminMembersRepository
from app.user.admin_members_service import AdminMembersService
from app.user.models import User, UserRole
from app.user.user_repository import UserRepository
from app.user.user_service import UserService


async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """단일 요청 스코프 트랜잭션 세션 (Spring 의 @Transactional 과 동일 의미).

    - 정상 종료(라우터가 응답 반환) → commit
    - 예외(BusinessError, ValidationError, 코드 버그 등) → rollback
    - finally 의 세션 close 는 `async with` 가 자동 처리

    repository 는 PK 를 즉시 써야 할 때 flush() 만 호출하고 commit 은 호출하지
    않는다 — 한 요청 = 한 트랜잭션 정책 (CLAUDE.md 모듈 규칙).
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


# ── 외부 어댑터 와이어링 ─────────────────────────────────
# settings.email_provider 에 따라 어댑터를 고른다. 테스트에선
# `app.dependency_overrides[get_email_sender] = lambda: ConsoleEmailSender()` 로 교체.


def build_email_sender(settings_obj: Settings) -> EmailSender:
    """settings 기반 EmailSender 인스턴스 빌더. 순수 함수라 DI 없이 단위 테스트 가능."""
    if settings_obj.email_provider == "gmail":
        if not (settings_obj.gmail_user and settings_obj.gmail_app_password):
            raise RuntimeError(
                "Gmail SMTP 설정 누락: GMAIL_USER / GMAIL_APP_PASSWORD 를 .env 에 채워주세요."
            )
        return GmailSmtpEmailSender(
            user=settings_obj.gmail_user,
            password=settings_obj.gmail_app_password,
            from_addr=settings_obj.email_from,
        )
    return ConsoleEmailSender()


@lru_cache
def _cached_email_sender() -> EmailSender:
    """프로세스 단위 싱글턴. Console 어댑터의 sent 누적을 유지하기 위함."""
    return build_email_sender(settings)


def get_email_sender() -> EmailSender:
    """FastAPI Depends() 진입점. router 는 `Depends(get_email_sender)` 로 받는다."""
    return _cached_email_sender()


def get_oauth_provider(provider: SocialProvider) -> OAuthProvider:
    """소셜 로그인 어댑터 팩토리 — router 가 path param 의 provider 를 풀어서 호출.

    Depends 로 직접 쓰지 않고 router 가 인자로 받아 직접 호출하는 방식
    (path param 에 의존하기 때문). 매 요청마다 새 인스턴스 — httpx 클라이언트는
    `async with` 로 어댑터 내부에서 관리됨.
    """
    return build_oauth_provider(provider, settings)


# ── 도메인 서비스 팩토리 ─────────────────────────────────
# router 는 Depends(get_<도메인>_service) 로 service 를 받는다. 다른 도메인도 같은
# 패턴으로 여기에 함수 한 개씩 추가.


async def get_auth_repository(
    session: AsyncSession = Depends(db_session),
) -> AuthRepository:
    """AuthRepository 팩토리. get_current_user 가 service 우회로 user 조회할 때 쓴다."""
    return AuthRepository(session)


async def get_auth_service(
    session: AsyncSession = Depends(db_session),
    email_sender: EmailSender = Depends(get_email_sender),
) -> AuthService:
    """AuthService 팩토리. session → Repository → Service 로 합성 + EmailSender + Redis 주입."""
    return AuthService(AuthRepository(session), email_sender=email_sender, redis=get_redis())


async def get_user_service(
    session: AsyncSession = Depends(db_session),
) -> UserService:
    """UserService 팩토리. session → UserRepository → UserService + PhoneVerifier + Redis."""
    redis = get_redis()
    return UserService(
        UserRepository(session), phone_verifier=OctomoPhoneVerifier(redis), redis=redis
    )


async def get_address_service(
    session: AsyncSession = Depends(db_session),
) -> AddressService:
    """AddressService 팩토리. session → AddressRepository → AddressService."""
    return AddressService(AddressRepository(session))


async def get_catalog_service(
    session: AsyncSession = Depends(db_session),
) -> CatalogService:
    """CatalogService 팩토리. session → CatalogRepository → CatalogService."""
    return CatalogService(CatalogRepository(session))


# ── 인증 dependency ─────────────────────────────────────
# 보호 endpoint 는 `Depends(get_current_user)` 또는 `Depends(get_active_user)` 로
# User 객체를 받는다. JPA 비유: Spring Security 의 `@AuthenticationPrincipal User user`.

bearer_scheme = HTTPBearer(auto_error=True)
"""Authorization: Bearer <token> 추출. 헤더 없으면 FastAPI 가 자동 401 처리."""


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    repo: AuthRepository = Depends(get_auth_repository),
) -> User:
    """access JWT 검증 → User 반환.

    Raises:
        TokenExpiredError (401): 토큰 만료/위조/refresh 토큰 오용 / sub 의 user 미존재.
        AccountInactiveError (403): 토큰은 유효하지만 계정이 비활성(탈퇴/정지).
    """
    payload = decode_token(credentials.credentials, expected_type="access")
    user = await repo.get_by_id(int(payload["sub"]))
    if user is None:
        # 토큰 발급 후 사용자가 삭제됐거나 sub 가 위조된 케이스. 정보 노출 최소화 위해 401.
        raise TokenExpiredError(message="존재하지 않는 사용자")
    if not user.is_active:
        raise AccountInactiveError()
    return user


async def get_active_user(
    user: User = Depends(get_current_user),
) -> User:
    """get_current_user + must_change_password=False 검증.

    임시 비번 발급 직후(`must_change_password=True`) 사용자는 비밀번호 변경 외
    모든 endpoint 에서 차단된다. 클라이언트는 PASSWORD_CHANGE_REQUIRED 응답을 받으면
    비밀번호 변경 페이지로 강제 redirect 해야 한다.

    사용 위치:
    - 비밀번호 변경 endpoint (POST /users/me/password) → `get_current_user` 사용 (이 가드 우회)
    - 그 외 모든 보호 endpoint                          → `get_active_user` 사용
    """
    if user.must_change_password:
        raise PasswordChangeRequiredError()
    return user


async def get_admin_user(
    user: User = Depends(get_active_user),
) -> User:
    """ADMIN 역할 전용 엔드포인트 가드. 관리자가 아니면 403 PermissionDeniedError."""
    if user.role != UserRole.ADMIN:
        raise PermissionDeniedError()
    return user


async def get_cart_service(
    session: AsyncSession = Depends(db_session),
) -> CartService:
    return CartService(CartRepository(session))


async def get_favorites_service(
    session: AsyncSession = Depends(db_session),
) -> FavoritesService:
    return FavoritesService(FavoritesRepository(session))


async def get_order_service(
    session: AsyncSession = Depends(db_session),
) -> OrderService:
    return OrderService(OrderRepository(session))


async def get_payment_service(
    session: AsyncSession = Depends(db_session),
    email_sender: EmailSender = Depends(get_email_sender),
) -> PaymentService:
    gateway: PaymentGateway
    if settings.use_fake_pg:
        from app.payment.adapters.fake import FakePaymentGateway

        gateway = FakePaymentGateway()
    else:
        from app.payment.adapters.toss import TossPaymentGateway

        gateway = TossPaymentGateway()
    return PaymentService(PaymentRepository(session), gateway, email_sender)


async def get_admin_catalog_service(
    session: AsyncSession = Depends(db_session),
) -> AdminCatalogService:
    return AdminCatalogService(CatalogRepository(session))


async def get_admin_members_service(
    session: AsyncSession = Depends(db_session),
) -> AdminMembersService:
    return AdminMembersService(AdminMembersRepository(session))


async def get_admin_order_service(
    session: AsyncSession = Depends(db_session),
) -> AdminOrderService:
    return AdminOrderService(AdminOrderRepository(session))


async def get_dashboard_service(
    session: AsyncSession = Depends(db_session),
) -> DashboardService:
    return DashboardService(session)


async def get_sales_service(
    session: AsyncSession = Depends(db_session),
) -> SalesService:
    return SalesService(session)


async def get_help_service(
    session: AsyncSession = Depends(db_session),
    email_sender: EmailSender = Depends(get_email_sender),
) -> HelpService:
    return HelpService(HelpRepository(session), email_sender)


async def get_admin_help_service(
    session: AsyncSession = Depends(db_session),
    email_sender: EmailSender = Depends(get_email_sender),
) -> AdminHelpService:
    return AdminHelpService(HelpRepository(session), email_sender)
