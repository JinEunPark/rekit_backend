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
        # 클라 SignUpView.vue 의 passwordValid 와 동일 규칙.
        if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
            raise ValueError("비밀번호는 영문과 숫자를 모두 포함해야 합니다.")
        return v

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


# ── 토큰 / 사용자 응답 ────────────────────────────────


class TokenResponse(BaseModel):
    """로그인/리프레시 응답 바디. refresh 는 별도 Set-Cookie 로 내려간다.

    serialization_alias 만 사용하는 이유:
    - 일반 alias 를 쓰면 __init__ 시그니처도 camelCase 로 강제돼서 내부 코드가
      TokenResponse(accessToken=...) 이라고 호출해야 함 (Python 관례 위반).
    - serialization_alias 는 출력 시(by_alias=True) 만 적용되므로 init 은
      snake_case 그대로 두면서 JSON 응답만 camelCase 로 직렬화 가능.
    """

    access_token: str = Field(serialization_alias="accessToken", description="JWT 액세스 토큰")
    token_type: str = Field(default="bearer", serialization_alias="tokenType")


class UserResponse(BaseModel):
    """사용자 프로필 응답. 클라 stores/auth.ts 의 User 타입과 동기화.

    GET /users/me 와 회원가입 응답이 재사용한다 (api.md §3.2, §4.1).

    필드 매핑:
    - User.identity_verified_at IS NOT NULL → verified=True (service 에서 계산해 주입)
    - eco_kg 는 누적 절약 kg — 별도 집계. 지금은 0 fallback.
    """

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


class SignUpResponse(BaseModel):
    """회원가입 응답 바디. api.md §3.2.

    user + accessToken 을 함께 반환해 클라가 가입 직후 GET /users/me 추가 호출 없이
    화면을 그릴 수 있게 한다. refresh 토큰은 sign-in 과 동일하게 Set-Cookie.
    """

    user: UserResponse
    access_token: str = Field(serialization_alias="accessToken")
