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

from fastapi import APIRouter, Cookie, Depends, Response, status

from app.auth.auth_schemas import (
    AvailabilityResponse,
    CheckLoginIdRequest,
    SignInRequest,
    SignUpRequest,
    SignUpResponse,
    TokenResponse,
    UserResponse,
)
from app.auth.auth_service import AuthService
from app.core.config import settings
from app.core.deps import get_auth_service
from app.core.exceptions import TokenExpired
from app.user.models import User

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
        httponly=True,                       # JS 접근 차단 (XSS 시 탈취 방어)
        secure=settings.is_production,       # dev(HTTP) 에선 False, prod 에선 True
        samesite="lax",                      # CSRF 완화. Strict 는 외부 링크 진입 시 끊김
        path=_refresh_cookie_path(),         # 다른 API 에는 쿠키 안 첨부 (노출 면적 축소)
    )


def _to_user_response(user: User) -> UserResponse:
    """User ORM 객체 → UserResponse DTO 변환.

    verified 는 컬럼이 아니라 identity_verified_at IS NOT NULL 로 계산 (요구사항
    정의서 §2.4). eco_kg 는 별도 집계 — 지금은 0 fallback.
    """
    return UserResponse(
        id=user.id,
        login_id=user.login_id,
        username=user.username,
        email=user.email,
        phone=user.phone,
        verified=user.identity_verified_at is not None,
    )


# ── 엔드포인트 ────────────────────────────────────────


@router.post(
    "/sign-up",
    response_model=SignUpResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="회원가입",
)
async def sign_up(
    body: SignUpRequest,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> SignUpResponse:
    """회원가입. api.md §3.2 + 클라 SignUpView.vue.

    응답:
    - user + accessToken: JSON body — 가입 직후 화면 그릴 때 추가 GET 불필요.
    - refresh_token: HttpOnly 쿠키.

    실패 케이스 → exception_handler 가 표준 포맷으로 변환:
    - UsernameTaken (409, USERNAME_TAKEN)
    - EmailTaken (409, EMAIL_TAKEN)
    - 검증 실패 (422, VALIDATION_ERROR)
    """
    user, access, refresh = await service.sign_up(
        login_id=body.login_id,
        username=body.username,
        password=body.password,
        email=body.email,
        agreed_marketing=body.agreed_marketing,
    )
    _set_refresh_cookie(response, refresh, settings.refresh_token_expire_days)
    return SignUpResponse(user=_to_user_response(user), access_token=access)


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
    access, refresh = await service.sign_in(
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
    return TokenResponse(access_token=access)


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

    new_access, new_refresh = await service.refresh_token(refresh_token)
    _set_refresh_cookie(response, new_refresh, settings.refresh_token_expire_days)
    return TokenResponse(access_token=new_access)


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
