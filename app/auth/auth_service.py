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

import logging
import secrets
import string
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import BackgroundTasks

from app.auth.adapters.ports import OAuthProvider
from app.auth.auth_repository import AuthRepository
from app.auth.auth_schemas import validate_password_policy
from app.auth.models import SocialAccount, SocialProvider
from app.common.email import EmailSender
from app.core.config import settings
from app.core.database import async_session_factory
from app.core.exceptions import (
    EmailTaken,
    InvalidCredentials,
    SocialEmailRequired,
    SocialOAuthFailed,
    UsernameTaken,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_social_signup_token,
    decode_social_signup_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.user.models import User, UserRole

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SocialLoginResult:
    """social_login 의 두 갈래 결과 — login OR needsSignUp.

    `temp_token` 가 None 이면 기존 사용자 로그인 (access/refresh 사용).
    None 이 아니면 신규 — 클라이언트는 약관 동의 후 `social_sign_up` 호출.
    """

    access_token: str | None
    refresh_token: str | None
    must_change_password: bool
    needs_sign_up: bool
    temp_token: str | None
    email: str | None
    suggested_name: str | None


class AuthService:
    def __init__(self, repo: AuthRepository, email_sender: EmailSender) -> None:
        self.repo = repo
        self.email_sender = email_sender

    # ── 로그인 ────────────────────────────────────────

    async def sign_in(
        self,
        login_id: str,
        password: str,
        remember: bool = False,
    ) -> tuple[str, str, bool]:
        """아이디+비밀번호 로그인.

        Returns:
            (access_token, refresh_token, must_change_password) 3-tuple.
            세 번째 값이 True 면 클라이언트는 비밀번호 변경 페이지로 강제 redirect
            해야 한다 — find-password 로 임시 비번을 받은 사용자.

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

        access, refresh = self._issue_tokens(user, remember=remember)
        return access, refresh, user.must_change_password

    # ── 회원가입 ──────────────────────────────────────

    async def sign_up(
        self,
        *,
        login_id: str,
        username: str,
        password: str,
        email: str,
        agreed_marketing: bool,
    ) -> User:
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

        now = datetime.now(UTC)
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

        return user

    async def is_login_id_available(self, login_id: str) -> bool:
        """로그인 아이디 사용 가능 여부 — /auth/check-login-id 의 도메인 로직."""
        return not await self.repo.exists_by_login_id(login_id)

    # ── 비밀번호 찾기 (임시 비번 발급) ──────────────────

    async def issue_temp_password(
        self,
        login_id: str,
        email: str,
        background_tasks: BackgroundTasks,
    ) -> None:
        """가입 정보(login_id + email) 일치 시 임시 비번 발급 작업을 BG 로 큐잉. api.md §3.8.

        실제 메일 발송 + DB 업데이트(password_hash, must_change_password) 는
        응답 후 BG task 가 자체 세션으로 처리한다 — 요청 트랜잭션이 SMTP 지연에
        묶이지 않게 (DB connection pool 점유 회피).

        **순서가 핵심**: BG task 는 이메일 발송이 성공한 경우에만 DB UPDATE 한다.
        이메일 실패 시 사용자의 기존 비번 그대로 — 이메일 없이 계정 잠기는 사고 방지.

        미가입 / 정보 불일치 시에도 예외 없이 조용히 반환 (enumeration 방어).
        """
        normalized = email.lower()
        user = await self.repo.get_by_login_id_and_email(login_id, normalized)
        if user is None:
            return  # 정보 불일치 — 조용히 무시. BG task 큐잉도 안 함.

        background_tasks.add_task(
            _bg_apply_temp_password,
            user_id=user.id,
            username=user.username,
            email=user.email,
            temp_password=_generate_temp_password(),
            email_sender=self.email_sender,
        )

    # ── 아이디 찾기 ─────────────────────────────────────

    async def find_login_id_by_email(
        self,
        email: str,
        background_tasks: BackgroundTasks,
    ) -> None:
        """가입 이메일로 아이디 발송 작업을 BG 로 큐잉. api.md §3.7.

        Read-only — DB 변경 없음. 이메일이 실패해도 사용자 상태에 영향 X.
        미가입 이메일이어도 조용히 반환 (enumeration 방어).
        """
        normalized = email.lower()
        user = await self.repo.get_by_email(normalized)
        if user is None:
            return

        background_tasks.add_task(
            _bg_send_login_id_email,
            to=user.email,
            username=user.username,
            login_id=user.login_id,
            email_sender=self.email_sender,
        )

    # ── 토큰 갱신 ─────────────────────────────────────

    async def refresh_token(self, refresh_token: str) -> tuple[str, str, bool]:
        """refresh JWT 검증 → 새 access + 새 refresh 발급 (rotation).

        Returns:
            (access, refresh, must_change_password) — sign_in 과 동일 형식.
            토큰 갱신 사이에 임시 비번 발급이 있었을 수도 있어 매번 user 상태에서
            읽어 응답에 실어준다 (false 로 굳어버리는 사고 방지).

        type='refresh' 가드가 access 를 refresh 자리에 못 쓰게 막는다.
        """
        payload = decode_token(refresh_token, expected_type="refresh")

        user = await self.repo.get_by_id(int(payload["sub"]))
        if user is None or not user.is_active:
            raise InvalidCredentials()

        access, refresh = self._issue_tokens(user, remember=False)
        return access, refresh, user.must_change_password

    # ── 소셜 로그인 ───────────────────────────────────

    async def social_login(
        self,
        provider: SocialProvider,
        oauth: OAuthProvider,
        code: str,
        state: str | None = None,
    ) -> SocialLoginResult:
        """OAuth code 교환 후 SocialAccount 매칭 → 로그인 OR needsSignUp 분기.

        흐름:
        1. oauth.exchange_code(code) — PG 로 토큰 교환 + 프로필 조회
        2. 프로필에 email 누락 시 SocialEmailRequired (422) raise
        3. (provider, social_id) 로 기존 연결 조회
           - 매칭: 즉시 로그인 (access/refresh 발급)
           - 미매칭: 신규 — temp_token 발급, 클라가 약관 동의 후 social_sign_up 호출

        Raises:
            SocialOAuthFailed (502): PG 와의 통신/인증 실패 (code 만료, redirect_uri
                불일치, 네트워크 오류 등). httpx 의 raw 예외를 도메인 예외로 변환해
                글로벌 핸들러가 표준 응답 + CORS 헤더로 내려보내게.
        """
        try:
            profile = await oauth.exchange_code(code, state)
        except httpx.HTTPStatusError as e:
            # 카카오/네이버/구글 token endpoint 가 4xx 응답 — 가장 흔한 케이스:
            # code 만료 (1분 초과), redirect_uri 콘솔 등록값 불일치, code 재사용.
            raise SocialOAuthFailed(
                message=f"소셜 로그인 PG 응답 오류 ({e.response.status_code})"
            ) from e
        except httpx.RequestError as e:
            # 타임아웃, DNS, TLS 등 네트워크 레이어 실패.
            raise SocialOAuthFailed(message=f"소셜 로그인 PG 통신 실패: {e}") from e

        if profile.email is None:
            raise SocialEmailRequired()

        existing = await self.repo.get_social_account(provider, profile.social_id)
        if existing is not None:
            user = await self.repo.get_by_id(existing.user_id)
            if user is None or not user.is_active:
                raise InvalidCredentials()
            access, refresh = self._issue_tokens(user, remember=False)
            return SocialLoginResult(
                access_token=access,
                refresh_token=refresh,
                must_change_password=user.must_change_password,
                needs_sign_up=False,
                temp_token=None,
                email=None,
                suggested_name=None,
            )

        temp_token = create_social_signup_token(
            provider=profile.provider,
            social_id=profile.social_id,
            email=profile.email,
            name=profile.name,
        )
        return SocialLoginResult(
            access_token=None,
            refresh_token=None,
            must_change_password=False,
            needs_sign_up=True,
            temp_token=temp_token,
            email=profile.email,
            suggested_name=profile.name,
        )

    async def social_sign_up(
        self,
        *,
        temp_token: str,
        login_id: str,
        username: str,
        agreed_marketing: bool,
    ) -> tuple[User, str, str]:
        """social_login 의 needsSignUp 응답을 받아 약관 동의 후 신규 가입.

        temp_token 의 (provider, social_id, email) 은 OAuth PG 가 검증한 값이라
        신뢰 가능. login_id / username / agreed_* 는 클라가 사용자에게 받아 전달.

        password_hash 는 더미 — 소셜 로그인만 가능하게 (랜덤 32자 bcrypt). 추후
        find-password 로 임시비번 발급 받으면 ID/PW 로그인도 가능.

        Returns:
            (user, access_token, refresh_token).

        Raises:
            UsernameTaken (409): login_id 중복.
            EmailTaken (409): email 중복 — 다른 사용자 이미 사용 중. 정책상 자동
                연결 안 함 (계정 탈취 위험).
            TokenExpired (401): temp_token 만료/위조.
        """
        payload = decode_social_signup_token(temp_token)
        provider_value: str = payload["provider"]
        social_id: str = payload["social_id"]
        email: str = payload["email"]

        if await self.repo.exists_by_login_id(login_id):
            raise UsernameTaken()
        if await self.repo.exists_by_email(email):
            raise EmailTaken()

        now = datetime.now(UTC)
        # password_hash 는 항상 hash 형태여야 NOT NULL 제약 통과. 사용자가 추측 불가한
        # 32자 랜덤을 hash — 소셜 로그인만 가능, ID/PW 로그인은 find-password 로 비번
        # 재발급 받으면 됨.
        random_password = secrets.token_urlsafe(24)
        user = User(
            login_id=login_id,
            username=username,
            email=email,
            password_hash=hash_password(random_password),
            role=UserRole.USER,
            is_active=True,
            must_change_password=False,
            agreed_terms_at=now,
            agreed_privacy_at=now,
            agreed_marketing_at=now if agreed_marketing else None,
        )
        user = await self.repo.add(user)

        social_account = SocialAccount(
            user_id=user.id,
            provider=SocialProvider(provider_value),
            social_id=social_id,
            email_at_link=email,
        )
        await self.repo.add_social_account(social_account)

        access, refresh = self._issue_tokens(user, remember=False)
        return user, access, refresh

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
            settings.refresh_token_remember_days if remember else settings.refresh_token_expire_days
        )
        refresh = create_refresh_token(
            sub=str(user.id),
            expires_in=timedelta(days=refresh_days),
        )
        return access, refresh


# ── 모듈 헬퍼 ────────────────────────────────────────────


_TEMP_PASSWORD_LENGTH = 16
_TEMP_PASSWORD_ALPHABET = string.ascii_letters + string.digits  # 62자 (62^16 ≈ 4.8e28)


def _generate_temp_password() -> str:
    """16자 영문+숫자 임시 비번. password 정책 자동 통과 보장.

    영문/숫자 한 쪽이 모두 빠질 확률은 2 * (36/62)^16 ≈ 4.6e-4 — 그 케이스만
    재시도. 정책 검증은 `validate_password_policy` 한 곳에서 관리해 SignUp /
    ChangePassword 와 silently 어긋나지 않도록.
    """
    while True:
        candidate = "".join(
            secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(_TEMP_PASSWORD_LENGTH)
        )
        try:
            return validate_password_policy(candidate)
        except ValueError:
            continue


# ── BackgroundTasks 본체 ─────────────────────────────────
# 응답 후 실행. 자체 DB session 을 열어 요청 트랜잭션과 분리 — SMTP 지연이
# 요청 connection 을 묶지 않도록. 실패 시 로그만 남기고 정상 종료 (사용자에게
# 별도 알림 X — find-id/find-password 는 enumeration 방어로 응답 통일).


async def _bg_send_login_id_email(
    *,
    to: str,
    username: str,
    login_id: str,
    email_sender: EmailSender,
) -> None:
    """find-id BG task — read-only. 이메일 실패해도 사용자 상태 영향 X."""
    try:
        await email_sender.send(
            to=to,
            subject="[Rekit] 아이디 안내",
            body=(
                f"{username}님, 안녕하세요.\n\n"
                f"회원님의 아이디는 {login_id} 입니다.\n\n"
                "본 메일은 발송 전용입니다."
            ),
        )
    except Exception:
        _log.exception("find-id email failed (to=%s)", to)


async def _bg_apply_temp_password(
    *,
    user_id: int,
    username: str,
    email: str,
    temp_password: str,
    email_sender: EmailSender,
) -> None:
    """find-password BG task — 이메일 발송 → 성공 시에만 user.password_hash + must_change UPDATE.

    순서가 핵심: 이메일이 실패하면 DB 손대지 않아 사용자가 기존 비번으로 계속
    로그인 가능. 사용자는 다시 find-password 를 호출하면 새 임시 비번 발급됨.
    """
    try:
        await email_sender.send(
            to=email,
            subject="[Rekit] 임시 비밀번호 안내",
            body=(
                f"{username}님, 안녕하세요.\n\n"
                f"임시 비밀번호: {temp_password}\n\n"
                "보안을 위해 임시 비밀번호로 로그인 후 즉시 새 비밀번호로 변경해주세요.\n"
                "임시 비밀번호 사용 중에는 비밀번호 변경 외 다른 기능을 이용할 수 없습니다.\n\n"
                "본 메일은 발송 전용입니다."
            ),
        )
    except Exception:
        _log.exception(
            "temp password email failed (user_id=%s) — DB 미변경", user_id
        )
        return

    async with async_session_factory() as session:
        try:
            user = await session.get(User, user_id)
            if user is None:
                _log.warning(
                    "temp password BG: user_id=%s 가 사라짐 (탈퇴?). 무시.", user_id
                )
                return
            user.password_hash = hash_password(temp_password)
            user.must_change_password = True
            await session.commit()
        except Exception:
            await session.rollback()
            _log.exception(
                "temp password DB update failed (user_id=%s) — 이메일은 발송됨",
                user_id,
            )
