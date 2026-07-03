"""표준 에러 포맷 + global handler.

api.md §1.3 / §1.5 의 응답 포맷:
    { "error": { "code": "...", "message": "...", "fields": {...} } }

서비스 레이어는 BusinessError 의 서브클래스를 raise 하면 된다.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

_log = logging.getLogger(__name__)


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


class SocialEmailRequired(BusinessError):
    """소셜 OAuth 콜백에서 이메일 동의가 빠진 경우.

    카카오 등은 사용자가 이메일 동의를 거부할 수 있는데 — 이메일이 없으면
    rekit 계정과 매핑할 수 없어 거절. 사용자는 PG 측에서 다시 이메일 동의 후 재시도.
    """

    code = "SOCIAL_EMAIL_REQUIRED"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "소셜 로그인에 이메일 동의가 필요합니다. 동의 후 다시 시도해주세요."


class SocialProviderNotConfigured(BusinessError):
    """해당 소셜 PG 의 client_id / secret / redirect_uri 가 .env 에 없는 상태.

    503 으로 응답해 운영 측에서 .env 채우면 즉시 복구되는 일시 상태임을 명시.
    """

    code = "SOCIAL_PROVIDER_NOT_CONFIGURED"
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "해당 소셜 로그인이 아직 활성화되지 않았습니다."


class SocialOAuthFailed(BusinessError):
    """소셜 PG 와의 통신/인증이 실패. token exchange 4xx/5xx, 네트워크 오류 등.

    502 (Bad Gateway) — 백엔드 자체 문제가 아니라 외부 PG 응답 이상이라는 의미.
    가장 흔한 원인: code 만료 (1분 초과 후 재호출) / redirect_uri 콘솔 등록값
    불일치 / 사용자가 동의 후 도중 취소.
    """

    code = "SOCIAL_OAUTH_FAILED"
    http_status = status.HTTP_502_BAD_GATEWAY
    message = "소셜 로그인 인증에 실패했습니다. 잠시 후 다시 시도해주세요."


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


class ProductNotFound(BusinessError):
    code = "PRODUCT_NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND
    message = "상품을 찾을 수 없습니다."


class CategoryNotFound(BusinessError):
    code = "CATEGORY_NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND
    message = "카테고리를 찾을 수 없습니다."


class CategoryAlreadyExists(BusinessError):
    code = "CATEGORY_ALREADY_EXISTS"
    http_status = status.HTTP_409_CONFLICT
    message = "이미 존재하는 카테고리 ID입니다."


class ProductUnavailable(BusinessError):
    """INACTIVE 또는 SOLD_OUT 상태 상품 — 주문 불가."""

    code = "PRODUCT_UNAVAILABLE"
    http_status = status.HTTP_400_BAD_REQUEST
    message = "현재 주문할 수 없는 상품입니다."


class OutOfStock(BusinessError):
    code = "OUT_OF_STOCK"
    http_status = status.HTTP_400_BAD_REQUEST
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


class AddressNotFound(BusinessError):
    code = "ADDRESS_NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND
    message = "배송지를 찾을 수 없습니다."


class AddressLimitExceeded(BusinessError):
    code = "ADDRESS_LIMIT_EXCEEDED"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "배송지는 최대 10개까지 등록할 수 있습니다."


class CartItemNotFound(BusinessError):
    code = "CART_ITEM_NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND
    message = "장바구니 항목을 찾을 수 없습니다."


class FavoriteNotFound(BusinessError):
    code = "FAVORITE_NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND
    message = "관심상품을 찾을 수 없습니다."


class OrderNotFound(BusinessError):
    code = "ORDER_NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND
    message = "주문을 찾을 수 없습니다."


class OrderCancelForbidden(BusinessError):
    code = "ORDER_CANCEL_FORBIDDEN"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "현재 상태에서는 주문을 취소할 수 없습니다."


class UserNotFound(BusinessError):
    code = "USER_NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND
    message = "사용자를 찾을 수 없습니다."


class InvalidOrderStatus(BusinessError):
    code = "INVALID_ORDER_STATUS"
    http_status = status.HTTP_409_CONFLICT
    message = "현재 상태에서는 해당 작업을 수행할 수 없습니다."


class RefundForbidden(BusinessError):
    code = "REFUND_FORBIDDEN"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "현재 상태에서는 환불을 요청할 수 없습니다."


class ShipmentNotFound(BusinessError):
    code = "SHIPMENT_NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND
    message = "배송 정보를 찾을 수 없습니다."


class InvalidVerificationCode(BusinessError):
    code = "INVALID_VERIFICATION_CODE"
    http_status = status.HTTP_400_BAD_REQUEST
    message = "인증 코드가 올바르지 않거나 만료되었습니다."


class VerificationRateLimited(BusinessError):
    code = "VERIFICATION_RATE_LIMITED"
    http_status = status.HTTP_429_TOO_MANY_REQUESTS
    message = "잠시 후 다시 시도해주세요. (1분에 1회)"


class PermissionDenied(BusinessError):
    code = "PERMISSION_DENIED"
    http_status = status.HTTP_403_FORBIDDEN
    message = "권한이 없습니다."


class NoticeNotFound(BusinessError):
    code = "NOTICE_NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND
    message = "공지사항을 찾을 수 없습니다."


class FaqNotFound(BusinessError):
    code = "FAQ_NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND
    message = "FAQ를 찾을 수 없습니다."


class ContactNotFound(BusinessError):
    code = "CONTACT_NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND
    message = "문의를 찾을 수 없습니다."


# ── handler 등록 ──────────────────────────────────────────────


def register_exception_handlers(app: FastAPI) -> None:
    """main.create_app 에서 호출. 모든 응답을 표준 포맷으로 통일한다."""

    @app.exception_handler(BusinessError)
    async def _business(_: Request, exc: BusinessError) -> JSONResponse:
        body: dict[str, object] = {"code": exc.code, "message": exc.message}
        if exc.fields:
            body["fields"] = exc.fields
        return JSONResponse(status_code=exc.http_status, content={"error": body})

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # 미처리 예외 — 표준 500 응답으로 변환. 핵심 이유 두 가지:
        # 1) Starlette 의 ServerErrorMiddleware 가 잡으면 응답이 CORS middleware
        #    바깥에서 만들어져 Access-Control-Allow-Origin 헤더가 누락 → 브라우저
        #    가 CORS 에러로 잘못 보고. 우리 핸들러가 잡으면 미들웨어 통과 정상.
        # 2) traceback 노출 차단 (debug=True 환경에서 raw 응답되는 거 방지).
        _log.exception("Unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "서버 오류가 발생했습니다.",
                }
            },
        )

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
