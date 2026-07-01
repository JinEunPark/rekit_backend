"""user 모듈 Pydantic 스키마 (DTO).

GET /users/me 응답은 [auth.UserResponse](../auth/auth_schemas.py) 를 그대로 재사용
(회원가입 응답과 동일 형태). 본 모듈은 user 고유 요청 DTO 만 정의한다.

비밀번호 정책은 [auth.validate_password_policy](../auth/auth_schemas.py) 한 곳에서
관리 — 정책 변경 시 두 군데 동기화 필요 없도록 import 해서 사용.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth.auth_schemas import PASSWORD_MIN_LENGTH, validate_password_policy


class UpdateProfileRequest(BaseModel):
    """PATCH /users/me 요청 바디. 변경할 필드만 전송 (partial update)."""

    username: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="변경할 사용자 이름",
    )
    phone: str | None = Field(
        default=None,
        pattern=r"^01[016789]\d{7,8}$",
        description="변경할 휴대폰 번호 (하이픈 없이 01012345678 형식)",
    )


class WithdrawRequest(BaseModel):
    """DELETE /users/me 요청 바디. 비밀번호 재확인으로 본인 확인."""

    password: str = Field(min_length=1, description="현재 비밀번호 (본인 확인용)")


class PhoneSendRequest(BaseModel):
    """POST /users/me/phone/send-verification 요청 바디."""

    phone: str = Field(
        pattern=r"^01[016789]\d{7,8}$",
        description="인증받을 휴대폰 번호 (하이픈 없이, 예: 01012345678)",
    )


class PhoneVerifyRequest(BaseModel):
    """POST /users/me/phone/verify 요청 바디."""

    phone: str = Field(
        pattern=r"^01[016789]\d{7,8}$",
        description="인증받은 휴대폰 번호",
    )
    code: str = Field(min_length=6, max_length=6, description="6자리 인증번호")


class ChangePasswordRequest(BaseModel):
    """POST /users/me/password 요청 바디. api.md §4.3 + 클라 ChangePasswordView.

    필드 매핑:
    - currentPassword → current_password (현재 비번 — 본인 확인)
    - newPassword     → new_password    (새 비번 — 정책 검증)

    `current_password` 에는 정책을 적용하지 않는다 — 임시 비번이거나 정책 변경
    이전에 만들어진 약한 비번일 수도 있어, 입력 길이 1+ 만 검증.
    """

    model_config = ConfigDict(populate_by_name=True)

    current_password: str = Field(
        min_length=1,
        validation_alias="currentPassword",
        description="현재 비밀번호 (본인 확인용)",
    )
    new_password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        validation_alias="newPassword",
        description="새 비밀번호 (영문+숫자 8자 이상)",
    )

    @field_validator("new_password")
    @classmethod
    def _new_password_policy(cls, v: str) -> str:
        return validate_password_policy(v)
