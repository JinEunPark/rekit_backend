"""auth 모듈 Service — 도메인 로직 레이어.

JPA 비유: @Service. 라우터(@RestController) 와 리포지토리(@Repository) 사이.

원칙 (CLAUDE.md 모듈 규칙):
- 외부 시스템(JWT, bcrypt, OTP, OAuth 등) 호출은 core/security 의 함수 또는
  ports/* Protocol 로만. SDK 직접 import 금지.
- 비즈니스 예외는 core/exceptions 에서 import 해서 raise. router 는 try/except
  로 잡지 않음 — FastAPI exception_handler 가 표준 응답 포맷으로 변환.
- 입력 정규화(email lowercase 등)는 여기서 한 번 더. schema 에서도 하지만,
  service 가 다른 코드(스크립트/관리자 도구)에서 직접 호출되는 경우 대비.
- 트랜잭션 경계는 router 의 db_session dependency 가 요청 1개 = 트랜잭션 1개로
  관리 — service 는 별도 commit/rollback 호출 X.

다른 도메인 service 도 이 패턴: Repository 주입 + 도메인 로직만.
"""

from datetime import datetime, timedelta, timezone

from app.auth.auth_repository import AuthRepository
from app.core.config import settings
from app.core.exceptions import (
    EmailTaken,
    InvalidCredentials,
    UsernameTaken,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.user.models import User, UserRole


class AuthService:
    def __init__(self, repo: AuthRepository) -> None:
        self.repo = repo

    # ── 로그인 ────────────────────────────────────────

    async def sign_in(
        self,
        login_id: str,
        password: str,
        remember: bool = False,
    ) -> tuple[str, str]:
        """아이디+비밀번호 로그인.

        Returns:
            (access_token, refresh_token) 튜플.

        Raises:
            InvalidCredentials: 다음 3가지 케이스 모두 같은 예외로 통합한다.
                - 존재하지 않는 아이디
                - 비밀번호 불일치
                - is_active=False (탈퇴/정지)
            이유: enumeration attack 방어 — "이 아이디 존재" 추론 차단.
        """
        user = await self.repo.get_by_login_id(login_id)
        if user is None or not user.is_active:
            raise InvalidCredentials()

        if not verify_password(password, user.password_hash):
            raise InvalidCredentials()

        return self._issue_tokens(user, remember=remember)

    # ── 회원가입 ──────────────────────────────────────

    async def sign_up(
        self,
        *,
        login_id: str,
        username: str,
        password: str,
        email: str,
        agreed_marketing: bool,
    ) -> tuple[User, str, str]:
        """회원가입. api.md §3.2.

        Args:
            login_id, username, password, email: schema 에서 검증 완료.
            agreed_marketing: 선택 약관. 필수 약관(terms/privacy)은 schema 에서
                반드시 True 가 보장되므로 service 가 다시 받지 않는다.

        Returns:
            (user, access_token, refresh_token).

        Raises:
            UsernameTaken (409): 동일 login_id 가 이미 존재.
            EmailTaken (409): 동일 email 이 이미 존재.
        """
        normalized_email = email.lower()

        # 중복은 login_id → email 순으로 체크. 두 검사 후에 INSERT 해도 race 시 DB
        # UNIQUE 가 최종 방어선이지만, 사전 체크가 일반 케이스의 UX 를 깔끔하게 함.
        if await self.repo.exists_by_login_id(login_id):
            raise UsernameTaken()
        if await self.repo.exists_by_email(normalized_email):
            raise EmailTaken()

        now = datetime.now(timezone.utc)
        # role/is_active 는 모델에 default 가 있지만 그건 DB INSERT 시점에만 적용된다.
        # 메모리에서 user.role 을 즉시 사용해야 하므로(토큰 claim) 명시적으로 지정.
        user = User(
            login_id=login_id,
            username=username,
            email=normalized_email,
            password_hash=hash_password(password),
            role=UserRole.USER,
            is_active=True,
            agreed_terms_at=now,
            agreed_privacy_at=now,
            agreed_marketing_at=now if agreed_marketing else None,
        )
        user = await self.repo.add(user)

        access, refresh = self._issue_tokens(user, remember=False)
        return user, access, refresh

    async def is_login_id_available(self, login_id: str) -> bool:
        """로그인 아이디 사용 가능 여부 — /auth/check-login-id 의 도메인 로직."""
        return not await self.repo.exists_by_login_id(login_id)

    # ── 토큰 갱신 ─────────────────────────────────────

    async def refresh_token(self, refresh_token: str) -> tuple[str, str]:
        """refresh JWT 검증 → 새 access + 새 refresh 발급 (rotation).

        type='refresh' 가드가 access 를 refresh 자리에 못 쓰게 막는다.
        """
        payload = decode_token(refresh_token, expected_type="refresh")

        user = await self.repo.get_by_id(int(payload["sub"]))
        if user is None or not user.is_active:
            raise InvalidCredentials()

        return self._issue_tokens(user, remember=False)

    # ── 내부 헬퍼 ─────────────────────────────────────

    def _issue_tokens(self, user: User, *, remember: bool) -> tuple[str, str]:
        """access + refresh 토큰 한 쌍 발급. sign_in / sign_up / refresh 공통.

        access: 짧은 만료, role claim 포함 (권한 변경 즉시 반영되도록).
        refresh: remember=True 면 30일, False 면 14일. 둘 다 stateless JWT.
        """
        access = create_access_token(
            sub=str(user.id),
            claims={"role": user.role.value},
        )
        refresh_days = (
            settings.refresh_token_remember_days
            if remember
            else settings.refresh_token_expire_days
        )
        refresh = create_refresh_token(
            sub=str(user.id),
            expires_in=timedelta(days=refresh_days),
        )
        return access, refresh
