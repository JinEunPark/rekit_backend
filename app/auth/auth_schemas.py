"""auth 모듈 Pydantic 스키마 (DTO).

라우터 ↔ 클라이언트 사이의 데이터 계약. service / repository 는 이 모듈을
import 하지 않는다 (역방향 의존 금지 — 응답 포맷이 바뀌어도 도메인 로직은 영향 X).

JPA 비유: @RequestBody 가 매핑되는 DTO + Bean Validation. 응답 DTO 는 @ResponseBody.

규칙 (다른 도메인 schemas.py 도 같은 패턴):
- 내부 필드는 snake_case, JSON 응답은 camelCase alias (api.md §1.3 응답 포맷).
- 검증은 Field(pattern, min_length, ...) 또는 @field_validator 로 선언적으로.
- ValidationError 는 FastAPI 가 자동으로 422 + VALIDATION_ERROR 표준 포맷으로 변환
  (app.core.exceptions._validation handler 참고) — 라우터에서 따로 try/except 안 함.

클라이언트 동기화 기준:
- rekle/src/views/auth/SignUpView.vue   (회원가입 폼)
- rekle/src/views/auth/SignInView.vue   (로그인 폼)
- rekle/src/stores/auth.ts              (User 타입)
"""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# 클라 SignUpView.vue 의 정규식과 1:1 동기화. 서버가 더 느슨하면 클라 통과 → 서버
# 거부로 UX 불일치, 서버가 더 빡세면 그 반대. 양쪽이 같아야 함.
LOGIN_ID_PATTERN = r"^[a-zA-Z0-9_]{4,20}$"
# 비밀번호 복잡도(영문+숫자 동시 포함)는 lookahead 가 필요한데 Pydantic v2 의 regex
# 엔진(Rust)은 lookahead 미지원 → field_validator 로 분리해서 검증한다.
PASSWORD_MIN_LENGTH = 8
# 사용자 이름. DB users.username NOT NULL VARCHAR(50). 한국어 이름 허용이라 정규식 X.
USERNAME_MIN_LENGTH = 1
USERNAME_MAX_LENGTH = 50


def validate_password_policy(v: str) -> str:
    """비밀번호 정책 검증 — 영문 + 숫자 동시 포함.

    SignUp / ChangePassword / ResetPassword 가 공통 사용. 한 곳에 두어 정책 변경 시
    silently 어긋나는 사고 방지. 클라(SignUpView.vue / ChangePasswordView.vue) 의
    passwordValid 와 동일 규칙.
    """
    if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
        raise ValueError("비밀번호는 영문과 숫자를 모두 포함해야 합니다.")
    return v


# ── 로그인 ────────────────────────────────────────────


class SignInRequest(BaseModel):
    """POST /auth/sign-in 요청 바디. api.md §3.3 + 클라 SignInView.vue.

    클라이언트가 loginId + password 를 보낸다. login_id 는 case-sensitive.
    """

    model_config = ConfigDict(populate_by_name=True)

    login_id: str = Field(
        min_length=1,
        validation_alias="loginId",
        description="로그인 아이디",
    )
    password: str = Field(min_length=1, description="평문 비밀번호")
    remember: bool = Field(
        default=False,
        description="True 면 refresh 토큰 만료 30일, False(기본)면 14일",
    )


# ── 회원가입 ──────────────────────────────────────────


class SignUpRequest(BaseModel):
    """POST /auth/sign-up 요청 바디. api.md §3.2 + 클라 SignUpView.vue.

    필드 매핑 (클라 camelCase → 서버 snake_case):
    - loginId         → login_id          (로그인 아이디)
    - agreedTerms     → agreed_terms      (필수)
    - agreedPrivacy   → agreed_privacy    (필수)
    - agreedMarketing → agreed_marketing  (선택)

    필수 약관(_terms / _privacy) 은 반드시 True. False 면 ValidationError → 422.
    """

    model_config = ConfigDict(populate_by_name=True)

    login_id: str = Field(
        pattern=LOGIN_ID_PATTERN,
        validation_alias="loginId",
        description="로그인 아이디 (영문·숫자·_ 4~20자)",
    )
    username: str = Field(
        min_length=USERNAME_MIN_LENGTH,
        max_length=USERNAME_MAX_LENGTH,
        description="사용자 이름 (표시용, 1~50자)",
    )
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        description="비밀번호 (영문+숫자 포함 8자 이상)",
    )
    email: EmailStr = Field(description="이메일 (비밀번호 찾기 등 본인 확인용)")
    agreed_terms: bool = Field(
        validation_alias="agreedTerms",
        description="이용약관 동의 (필수)",
    )
    agreed_privacy: bool = Field(
        validation_alias="agreedPrivacy",
        description="개인정보 수집·이용 동의 (필수)",
    )
    agreed_marketing: bool = Field(
        default=False,
        validation_alias="agreedMarketing",
        description="마케팅 정보 수신 동의 (선택)",
    )

    @field_validator("email")
    @classmethod
    def _lowercase_email(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    @classmethod
    def _password_must_have_letter_and_digit(cls, v: str) -> str:
        return validate_password_policy(v)

    @field_validator("agreed_terms", "agreed_privacy")
    @classmethod
    def _must_be_true(cls, v: bool) -> bool:
        # 필수 약관 미동의는 비즈니스 규칙 위반. ValidationError 로 422 변환.
        if not v:
            raise ValueError("필수 약관에 동의해야 합니다.")
        return v


# ── 아이디 중복확인 ───────────────────────────────────


class CheckLoginIdRequest(BaseModel):
    """POST /auth/check-login-id 요청 바디. 클라 SignUpView.vue 의 [중복확인] 버튼."""

    model_config = ConfigDict(populate_by_name=True)

    login_id: str = Field(
        pattern=LOGIN_ID_PATTERN,
        validation_alias="loginId",
        description="중복 검사할 로그인 아이디",
    )


class AvailabilityResponse(BaseModel):
    """리소스 가용 여부 응답. /auth/check-username 에서 사용.

    범용 이름으로 둠 — 추후 닉네임/이메일 중복확인이 추가돼도 재사용 가능.
    """

    available: bool = Field(description="사용 가능하면 True, 이미 사용 중이면 False")


# ── 아이디 / 비번 찾기 ─────────────────────────────────


class FindIdRequest(BaseModel):
    """POST /auth/find-id 요청 바디. api.md §3.7. Public.

    가입 이메일을 받아 동일 이메일 inbox 로 아이디를 발송한다 — 화면 노출 X.
    가입 여부와 무관하게 응답이 동일하므로 enumeration 방어 가능.
    """

    email: EmailStr = Field(description="가입 시 등록한 이메일")


class FindPasswordRequest(BaseModel):
    """POST /auth/find-password 요청 바디. api.md §3.8. Public.

    loginId + email 둘 다 일치해야 임시 비번 발급 — 한 쪽만 알아도 임시 비번을
    받을 수 없게 해서, 이메일이나 아이디 단편 정보로 계정 탈취되는 시나리오 차단.
    """

    model_config = ConfigDict(populate_by_name=True)

    login_id: str = Field(
        min_length=1,
        validation_alias="loginId",
        description="가입 아이디",
    )
    email: EmailStr = Field(description="가입 시 등록한 이메일")


# ── 소셜 로그인 ────────────────────────────────────────


class SocialCallbackRequest(BaseModel):
    """POST /auth/social/{provider}/callback 요청 바디. api.md §3.6.

    프론트에서 PG 동의 화면 redirect 후 ?code=...&state=... 를 받아 그대로 전달.
    state 검증은 프론트 책임이지만 네이버 token exchange 에 필수라 그대로 통과.
    """

    code: str = Field(min_length=1, description="OAuth authorization code")
    state: str | None = Field(
        default=None, description="OAuth state — 네이버는 필수, 카카오/구글은 옵션"
    )


class SocialCallbackResponse(BaseModel):
    """소셜 콜백 응답 — login OR needsSignUp 두 갈래.

    `needsSignUp=false`: 기존 사용자 — accessToken/tokenType/mustChangePassword 채움.
    `needsSignUp=true`: 신규 — tempToken/email/suggestedName 채움. 클라는 약관
    동의 화면 표시 후 POST /auth/social/sign-up 호출.
    """

    model_config = ConfigDict(populate_by_name=True)

    needs_sign_up: bool = Field(serialization_alias="needsSignUp")

    # 기존 사용자 로그인 시 채워짐
    access_token: str | None = Field(default=None, serialization_alias="accessToken")
    token_type: str | None = Field(default=None, serialization_alias="tokenType")
    must_change_password: bool | None = Field(
        default=None, serialization_alias="mustChangePassword"
    )

    # 신규 사용자 (needsSignUp=true) 시 채워짐
    temp_token: str | None = Field(default=None, serialization_alias="tempToken")
    email: str | None = Field(default=None)
    suggested_name: str | None = Field(default=None, serialization_alias="suggestedName")


class SocialSignUpRequest(BaseModel):
    """POST /auth/social/sign-up — 소셜 신규가입 완료 (약관 동의 + login_id 결정).

    `tempToken` 안에 (provider, social_id, email) 가 들어있어 OAuth PG 가 검증한
    값임이 보장된다. 사용자는 login_id / 표시 이름 / 약관 동의만 추가 입력.
    """

    model_config = ConfigDict(populate_by_name=True)

    temp_token: str = Field(min_length=10, validation_alias="tempToken")
    login_id: str = Field(
        pattern=LOGIN_ID_PATTERN,
        validation_alias="loginId",
        description="로그인 아이디 (영문·숫자·_ 4~20자)",
    )
    username: str = Field(
        min_length=USERNAME_MIN_LENGTH,
        max_length=USERNAME_MAX_LENGTH,
        description="표시 이름",
    )
    agreed_terms: bool = Field(validation_alias="agreedTerms")
    agreed_privacy: bool = Field(validation_alias="agreedPrivacy")
    agreed_marketing: bool = Field(default=False, validation_alias="agreedMarketing")

    @field_validator("agreed_terms", "agreed_privacy")
    @classmethod
    def _must_be_true(cls, v: bool) -> bool:
        if not v:
            raise ValueError("필수 약관에 동의해야 합니다.")
        return v


class SentResponse(BaseModel):
    """범용 발송-성공 응답. find-id / find-password 등이 사용한다.

    가입 여부에 따라 실제 발송 동작은 분기되지만, 클라가 보는 응답은 항상 동일 —
    enumeration 정보 누설 방지.
    `masked_email` 은 클라가 입력한 이메일을 그대로 마스킹한 값이라 서버 결과에
    의존하지 않는다. (서버가 가입 여부를 확인 후 채우는 게 아님)
    """

    model_config = ConfigDict(populate_by_name=True)

    sent: bool = Field(description="요청 처리됨. 항상 True (실제 발송 여부와 무관)")
    masked_email: str | None = Field(
        default=None,
        serialization_alias="maskedEmail",
        description="입력 이메일 마스킹 결과. find-password 에서만 채워짐",
    )


# ── 토큰 / 사용자 응답 ────────────────────────────────


class TokenResponse(BaseModel):
    """로그인/리프레시 응답 바디. refresh 는 별도 Set-Cookie 로 내려간다.

    serialization_alias 만 사용하는 이유:
    - 일반 alias 를 쓰면 __init__ 시그니처도 camelCase 로 강제돼서 내부 코드가
      TokenResponse(accessToken=...) 이라고 호출해야 함 (Python 관례 위반).
    - serialization_alias 는 출력 시(by_alias=True) 만 적용되므로 init 은
      snake_case 그대로 두면서 JSON 응답만 camelCase 로 직렬화 가능.

    `must_change_password=True` 가 응답에 실리면 클라이언트는 비밀번호 변경
    페이지로 강제 redirect 해야 한다 — find-password 로 임시 비번을 받은
    사용자가 로그인했을 때만 True 가 된다 (Phase G/E 가드와 짝).
    """

    access_token: str = Field(serialization_alias="accessToken", description="JWT 액세스 토큰")
    token_type: str = Field(default="bearer", serialization_alias="tokenType")
    must_change_password: bool = Field(
        default=False,
        serialization_alias="mustChangePassword",
        description="True 면 클라가 비밀번호 변경 페이지로 강제 redirect",
    )


class UserResponse(BaseModel):
    """사용자 프로필 응답. 클라 stores/auth.ts 의 User 타입과 동기화.

    GET /users/me 와 회원가입 응답이 재사용한다 (api.md §3.2, §4.1).

    `from_attributes=True` 로 ORM 객체에서 직접 매핑된다 — 라우터는
    UserResponse.model_validate(user) 한 줄로 변환한다.
    `verified` 는 User.verified @property (= identity_verified_at IS NOT NULL) 가
    그대로 들어온다. eco_kg 는 별도 집계 — 지금은 0 fallback.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="사용자 PK")
    login_id: str = Field(serialization_alias="loginId", description="로그인 아이디")
    username: str = Field(description="사용자 이름 (표시용)")
    email: EmailStr = Field(description="이메일")
    phone: str | None = Field(default=None, description="휴대폰. 본인인증 후 채워짐")
    verified: bool = Field(description="본인인증 완료 여부")
    eco_kg: int = Field(
        default=0,
        serialization_alias="ecoKg",
        description="누적 절약 kg (집계 결과)",
    )
