"""표준 에러 포맷 + global handler.

api.md §1.3 / §1.5 의 응답 포맷:
    { "error": { "code": "...", "message": "...", "fields": {...} } }

서비스 레이어는 BusinessError 의 서브클래스를 raise 하면 된다.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class BusinessError(Exception):
    """비즈니스 예외 베이스. api.md §1.5 의 에러 코드와 1:1 매핑."""

    code: str = "INTERNAL_ERROR"
    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    message: str = "서버 오류가 발생했습니다."

    def __init__(
        self,
        message: str | None = None,
        *,
        fields: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.fields = fields


# ── api.md §1.5 매핑된 구체 예외 ──────────────────────────────


class InvalidCredentials(BusinessError):
    code = "INVALID_CREDENTIALS"
    http_status = status.HTTP_401_UNAUTHORIZED
    message = "아이디 또는 비밀번호가 올바르지 않습니다."


class TokenExpired(BusinessError):
    code = "TOKEN_EXPIRED"
    http_status = status.HTTP_401_UNAUTHORIZED
    message = "토큰이 만료되었습니다."


class AccountInactive(BusinessError):
    """비활성화된 계정의 인증된 호출. 토큰은 유효하지만 권한 없음 → 403."""

    code = "ACCOUNT_INACTIVE"
    http_status = status.HTTP_403_FORBIDDEN
    message = "계정이 비활성화 상태입니다."


class PasswordChangeRequired(BusinessError):
    """임시 비밀번호로 발급된 상태(must_change_password=True) — 비번 변경 외 차단.

    클라이언트는 이 코드를 받으면 비밀번호 변경 페이지로 강제 redirect 한다.
    """

    code = "PASSWORD_CHANGE_REQUIRED"
    http_status = status.HTTP_403_FORBIDDEN
    message = "임시 비밀번호 사용 중입니다. 새 비밀번호로 변경 후 이용해주세요."


class UsernameTaken(BusinessError):
    code = "USERNAME_TAKEN"
    http_status = status.HTTP_409_CONFLICT
    message = "이미 사용 중인 아이디입니다."


class EmailTaken(BusinessError):
    code = "EMAIL_TAKEN"
    http_status = status.HTTP_409_CONFLICT
    message = "이미 사용 중인 이메일입니다."


class IdentityRequired(BusinessError):
    code = "IDENTITY_REQUIRED"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "본인인증이 필요합니다."


class OutOfStock(BusinessError):
    code = "OUT_OF_STOCK"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "재고가 부족합니다."


class PriceChanged(BusinessError):
    code = "PRICE_CHANGED"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "상품 가격이 변경되었습니다."


class PaymentFailed(BusinessError):
    code = "PAYMENT_FAILED"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "결제가 실패했습니다."


class OtpInvalid(BusinessError):
    code = "OTP_INVALID"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "인증번호가 일치하지 않거나 만료되었습니다."


class OtpRateLimited(BusinessError):
    code = "OTP_RATE_LIMITED"
    http_status = status.HTTP_429_TOO_MANY_REQUESTS
    message = "OTP 발송 한도를 초과했습니다."


class RateLimited(BusinessError):
    code = "RATE_LIMITED"
    http_status = status.HTTP_429_TOO_MANY_REQUESTS
    message = "요청 한도를 초과했습니다."


# ── handler 등록 ──────────────────────────────────────────────


def register_exception_handlers(app: FastAPI) -> None:
    """main.create_app 에서 호출. 모든 응답을 표준 포맷으로 통일한다."""

    @app.exception_handler(BusinessError)
    async def _business(_: Request, exc: BusinessError) -> JSONResponse:
        body: dict[str, object] = {"code": exc.code, "message": exc.message}
        if exc.fields:
            body["fields"] = exc.fields
        return JSONResponse(status_code=exc.http_status, content={"error": body})

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic 검증 실패 → 비즈니스 에러와 동일한 wrapper 로 통일.
        # fields[name] 는 사용자에게 그대로 보여줄 한국어 메시지 (string).
        # @field_validator 의 raise ValueError("...") 메시지가 그대로 들어간다.
        # 빌트인 제약(min_length, pattern 등) 은 Pydantic 기본 영어 메시지가 노출됨 —
        # 한국어로 보이게 하려면 해당 필드를 @field_validator 로 옮길 것.
        fields: dict[str, str] = {}
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"] if p != "body")
            fields[loc or "body"] = _strip_value_error_prefix(err["msg"])
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "입력값을 확인해주세요.",
                    "fields": fields,
                }
            },
        )


# Pydantic v2 는 @field_validator 내부에서 raise 한 ValueError 메시지에
# "Value error, " 접두어를 자동으로 붙인다. 사용자에게 노출하기 전에 제거.
_VALUE_ERROR_PREFIX = "Value error, "


def _strip_value_error_prefix(msg: str) -> str:
    if msg.startswith(_VALUE_ERROR_PREFIX):
        return msg[len(_VALUE_ERROR_PREFIX) :]
    return msg
