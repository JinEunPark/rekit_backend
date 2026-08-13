"""user 모듈 Pydantic 스키마 (DTO).

GET /users/me 응답은 [auth.UserResponse](../auth/auth_schemas.py) 를 그대로 재사용
(회원가입 응답과 동일 형태). 본 모듈은 user 고유 요청 DTO 만 정의한다.

비밀번호 정책은 [auth.validate_password_policy](../auth/auth_schemas.py) 한 곳에서
관리 — 정책 변경 시 두 군데 동기화 필요 없도록 import 해서 사용.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth.auth_schemas import PASSWORD_MIN_LENGTH, validate_password_policy
from app.core.phone import OptionalPhoneStr, PhoneStr


class UpdateProfileRequest(BaseModel):
    """PATCH /users/me 요청 바디. 변경할 필드만 전송 (partial update)."""

    username: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="변경할 사용자 이름",
    )
    phone: OptionalPhoneStr = Field(
        default=None,
        description="변경할 휴대폰 번호 (하이픈 유무 무관, 010-1234-5678 형식으로 저장)",
    )


class WithdrawRequest(BaseModel):
    """DELETE /users/me 요청 바디. 비밀번호 재확인으로 본인 확인."""

    password: str = Field(min_length=1, description="현재 비밀번호 (본인 확인용)")


class PhoneSendRequest(BaseModel):
    """POST /users/me/phone/send-verification 요청 바디."""

    phone: PhoneStr = Field(
        description="인증받을 휴대폰 번호 (하이픈 유무 무관, 010-1234-5678 형식으로 저장)",
    )


class PhoneSendResponse(BaseModel):
    """POST /users/me/phone/send-verification 응답 바디.

    Octomo 는 서버가 SMS 를 발송하지 않는다 — QR 이미지를 발급해 프론트에
    보여주고, 사용자가 직접 카메라로 스캔해 문자를 전송해야 한다.
    """

    qr_code: str = Field(
        serialization_alias="qrCode",
        description="data:image/png;base64,... — 프론트가 <img> 로 바로 표시",
    )


class PhoneVerifyRequest(BaseModel):
    """POST /users/me/phone/verify 요청 바디.

    Octomo QR 방식이라 사용자가 인증코드 값을 본 적이 없다(문자 앱에 이미
    채워진 채로 전송만 함) — 그래서 code 필드가 없다. 서버가 발급해둔 코드를
    스스로 재조회해서 검증한다.
    """

    phone: PhoneStr = Field(
        description="인증받은 휴대폰 번호 (하이픈 유무 무관, 010-1234-5678 형식으로 저장)",
    )


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
