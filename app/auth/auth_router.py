"""auth 모듈 Router — HTTP 엔드포인트.

JPA 비유: @RestController + @RequestMapping("/auth").

규칙 (CLAUDE.md 모듈 규칙):
- 비즈니스 로직 금지. service 호출만.
- prefix 는 자기 도메인만 ('/auth'). 상위 prefix(api/v1)는 main.py 가 붙임.
- 의존성은 Depends(get_*_service) 팩토리로 주입 — 테스트에서 fake 로 교체 쉬움.
- 응답은 Pydantic 모델로 (직접 dict 반환 금지). response_model 명시.

다른 도메인 router 도 이 파일 패턴을 따라 작성:
1) APIRouter(prefix=도메인, tags=[도메인])
2) @router.<verb>(path, response_model=..., status_code=..., summary=...)
3) async def 안에서 service 호출 후 응답 객체 반환
"""

from fastapi import APIRouter, Cookie, Depends, Path, Response, status

from app.auth.adapters.ports import OAuthProvider
from app.auth.auth_schemas import (
    AvailabilityResponse,
    CheckLoginIdRequest,
    FindIdRequest,
    FindPasswordRequest,
    SentResponse,
    SignInRequest,
    SignUpRequest,
    SocialCallbackRequest,
    SocialCallbackResponse,
    SocialSignUpRequest,
    TokenResponse,
    UserResponse,
)
from app.auth.auth_service import AuthService
from app.auth.models import SocialProvider
from app.core.config import settings
from app.core.deps import get_auth_service, get_oauth_provider
from app.core.exceptions import TokenExpired

router = APIRouter(prefix="/auth", tags=["auth"])


# ── 쿠키 헬퍼 ─────────────────────────────────────────
# refresh 쿠키 set/delete 옵션을 한 곳에 모은다.
# 이유: 쿠키 식별 키 = (name + path + domain). sign-in 이 path=/api/v1/auth 로 set
# 하면 sign-out 도 같은 path 로 delete 해야 삭제됨. 흩어두면 path 가 어긋나서 쿠키
# 가 안 지워지는 흔한 버그가 발생 — 헬퍼로 강제 동기화.


def _refresh_cookie_path() -> str:
    return f"{settings.api_v1_prefix}/auth"


def _set_refresh_cookie(response: Response, token: str, max_age_days: int) -> None:
    response.set_cookie(
        key="refresh_token",
        value=token,
        max_age=max_age_days * 24 * 60 * 60,
        httponly=True,  # JS 접근 차단 (XSS 시 탈취 방어)
        secure=settings.is_production,  # dev(HTTP) 에선 False, prod 에선 True
        samesite="lax",  # CSRF 완화. Strict 는 외부 링크 진입 시 끊김
        path=_refresh_cookie_path(),  # 다른 API 에는 쿠키 안 첨부 (노출 면적 축소)
    )


# ── 엔드포인트 ────────────────────────────────────────


@router.post(
    "/sign-up",
    response_model=UserResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="회원가입",
)
async def sign_up(
    body: SignUpRequest,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    """회원가입. api.md §3.2 + 클라 SignUpView.vue.

    응답:
    - user + accessToken: JSON body — 가입 직후 화면 그릴 때 추가 GET 불필요.
    - refresh_token: HttpOnly 쿠키.

    실패 케이스 → exception_handler 가 표준 포맷으로 변환:
    - UsernameTaken (409, USERNAME_TAKEN)
    - EmailTaken (409, EMAIL_TAKEN)
    - 검증 실패 (422, VALIDATION_ERROR)
    """
    user = await service.sign_up(
        login_id=body.login_id,
        username=body.username,
        password=body.password,
        email=body.email,
        agreed_marketing=body.agreed_marketing,
    )
    return UserResponse.model_validate(user)


@router.post(
    "/check-login-id",
    response_model=AvailabilityResponse,
    status_code=status.HTTP_200_OK,
    summary="로그인 아이디 중복 확인",
)
async def check_login_id(
    body: CheckLoginIdRequest,
    service: AuthService = Depends(get_auth_service),
) -> AvailabilityResponse:
    """가입 화면 [중복확인] 버튼.

    available=True → 사용 가능 / False → 이미 사용 중.
    """
    available = await service.is_login_id_available(body.login_id)
    return AvailabilityResponse(available=available)


@router.post(
    "/find-id",
    response_model=SentResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_200_OK,
    summary="아이디 찾기 — 가입 이메일로 아이디 발송",
)
async def find_id(
    body: FindIdRequest,
    service: AuthService = Depends(get_auth_service),
) -> SentResponse:
    """아이디 찾기. api.md §3.7. Public.

    가입된 이메일이면 해당 이메일 inbox 로 아이디를 보낸다. 가입자가 아니어도
    동일 응답을 반환해 가입 여부를 응답으로 추론할 수 없게 한다 (enumeration 방어).
    """
    await service.find_login_id_by_email(body.email)
    return SentResponse(sent=True)


@router.post(
    "/find-password",
    response_model=SentResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_200_OK,
    summary="비밀번호 찾기 — 임시 비밀번호 메일 발송",
)
async def find_password(
    body: FindPasswordRequest,
    service: AuthService = Depends(get_auth_service),
) -> SentResponse:
    """비밀번호 찾기 (임시 비번 발급). api.md §3.8. Public.

    loginId + email 매칭 시 임시 비번 발급 + 메일 발송. 매칭 실패해도 응답 동일.
    `maskedEmail` 은 입력값을 그대로 마스킹한 값이라 가입자/미가입자 동일
    (서버 검증 결과 아님 — enumeration 방어).
    """
    await service.issue_temp_password(login_id=body.login_id, email=body.email)
    return SentResponse(sent=True, masked_email=_mask_email(body.email))


def _mask_email(email: str) -> str:
    """이메일 마스킹 (입력값 그대로 — 서버 검증 결과 아님).

    aaa@example.com → a**@example.com / abcdef@example.com → ab****@example.com
    local 길이 1 이면 그대로 (1자만 가리는 건 의미 없음).
    """
    local, _, domain = email.partition("@")
    if len(local) <= 1:
        return f"{local}@{domain}"
    visible = max(1, len(local) // 3)  # 6자면 2자, 3자면 1자, 9자면 3자 노출
    return f"{local[:visible]}{'*' * (len(local) - visible)}@{domain}"


@router.post(
    "/sign-in",
    response_model=TokenResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_200_OK,
    summary="로그인 (아이디+비밀번호)",
)
async def sign_in(
    body: SignInRequest,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """아이디/비밀번호 로그인. api.md §3.3.

    응답:
    - access_token: JSON body
    - refresh_token: HttpOnly 쿠키 (Set-Cookie)

    실패 시 service 가 InvalidCredentials 를 raise → exception_handler 가
    401 + INVALID_CREDENTIALS 표준 포맷으로 자동 변환.
    """
    access, refresh, must_change = await service.sign_in(
        login_id=body.login_id,
        password=body.password,
        remember=body.remember,
    )

    refresh_max_age_days = (
        settings.refresh_token_remember_days
        if body.remember
        else settings.refresh_token_expire_days
    )
    _set_refresh_cookie(response, refresh, refresh_max_age_days)
    return TokenResponse(access_token=access, must_change_password=must_change)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_200_OK,
    summary="액세스 토큰 갱신",
)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """refresh 쿠키로 access 갱신 + refresh rotation. api.md §3.5.

    Cookie() 의 동작:
    - 파라미터 이름(refresh_token) = 쿠키 이름. 일치하는 쿠키만 자동 추출.
    - default=None 이면 쿠키가 없을 때 422 대신 None 으로 들어옴 → 직접 401 처리.
    """
    if refresh_token is None:
        raise TokenExpired(message="refresh 쿠키가 없습니다.")

    new_access, new_refresh, must_change = await service.refresh_token(refresh_token)
    _set_refresh_cookie(response, new_refresh, settings.refresh_token_expire_days)
    return TokenResponse(access_token=new_access, must_change_password=must_change)


@router.post(
    "/sign-out",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="로그아웃 (쿠키 삭제)",
)
async def sign_out(response: Response) -> None:
    """refresh 쿠키 폐기. api.md §3.4.

    stateless JWT 한계로 access 를 즉시 무효화하지는 못함 (만료까지 유효).
    Redis 세션 도입 시 여기에 jti revoke 추가 예정.

    delete_cookie 는 path 가 일치해야 동작 — _refresh_cookie_path() 로 강제 동기화.
    비로그인 상태에서 호출돼도 멱등 (이미 없는 쿠키 지우기 = no-op).
    """
    response.delete_cookie(key="refresh_token", path=_refresh_cookie_path())


# ── 소셜 로그인 ────────────────────────────────────────


@router.post(
    "/social/{provider}/callback",
    response_model=SocialCallbackResponse,
    response_model_by_alias=True,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
    summary="소셜 로그인 콜백 — code 교환 후 로그인 또는 신규가입 분기",
)
async def social_callback(
    body: SocialCallbackRequest,
    response: Response,
    provider: SocialProvider = Path(description="kakao | naver | google"),
    oauth: OAuthProvider = Depends(get_oauth_provider),
    service: AuthService = Depends(get_auth_service),
) -> SocialCallbackResponse:
    """카카오/네이버/구글 OAuth 콜백. api.md §3.6. Public.

    프론트가 PG 동의 화면에서 받은 ?code (네이버는 + state) 를 그대로 전달하면,
    서버가 PG 토큰 교환 + 프로필 조회 후:
    - 기존 연결 사용자: accessToken/mustChangePassword 응답 + refresh 쿠키 set
    - 신규: needsSignUp=true + tempToken/email/suggestedName

    Errors → exception_handler:
    - SocialEmailRequired (422): 이메일 동의 누락 — PG 측에서 다시 동의 후 재시도.
    - SocialProviderNotConfigured (503): 해당 provider 의 .env 설정 누락.
    - InvalidCredentials (401): 비활성 사용자.
    """
    result = await service.social_login(provider, oauth, body.code, body.state)

    if result.needs_sign_up:
        return SocialCallbackResponse(
            needs_sign_up=True,
            temp_token=result.temp_token,
            email=result.email,
            suggested_name=result.suggested_name,
        )

    # 기존 사용자 로그인 — refresh 쿠키 set
    assert result.refresh_token is not None  # needs_sign_up=False 때만
    _set_refresh_cookie(response, result.refresh_token, settings.refresh_token_expire_days)
    return SocialCallbackResponse(
        needs_sign_up=False,
        access_token=result.access_token,
        token_type="bearer",
        must_change_password=result.must_change_password,
    )


@router.post(
    "/social/sign-up",
    response_model=TokenResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="소셜 신규가입 완료 (tempToken + 약관 동의 + login_id)",
)
async def social_sign_up(
    body: SocialSignUpRequest,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """소셜 콜백에서 받은 tempToken 으로 신규 가입 마무리. api.md §3.6 후속.

    tempToken 안의 (provider, social_id, email) 은 PG 가 검증한 값이라 신뢰
    가능. 사용자는 login_id / 표시이름 / 약관만 입력. 가입 후 즉시 로그인 토큰 응답.

    Errors:
    - UsernameTaken (409) / EmailTaken (409): 입력 login_id 또는 tempToken 의
      email 이 이미 사용 중.
    - TokenExpired (401): tempToken 만료/위조.
    - 검증 실패 (422): login_id 형식, 약관 미동의.
    """
    user, access, refresh = await service.social_sign_up(
        temp_token=body.temp_token,
        login_id=body.login_id,
        username=body.username,
        agreed_marketing=body.agreed_marketing,
    )
    del user  # router 응답엔 토큰만 (UserResponse 가 필요하면 별도 반환 가능)

    _set_refresh_cookie(response, refresh, settings.refresh_token_expire_days)
    return TokenResponse(access_token=access, must_change_password=False)
