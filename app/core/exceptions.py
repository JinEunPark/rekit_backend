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
        # Pydantic 검증 실패 → 표준 포맷으로 변환
        fields: dict[str, str] = {}
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"] if p != "body")
            fields[loc or "body"] = err["type"].upper()
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "요청 형식이 올바르지 않습니다.",
                    "fields": fields,
                }
            },
        )
