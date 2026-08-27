
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import ExpiredSignatureError, JWTError, jwt

from app.core.config import settings
from app.core.exceptions import TokenExpiredError


def hash_password(plain: str) -> str:
    """bcrypt 해시. 결과는 60자 고정, '$2b$12$...' 형식."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """저장된 해시와 평문 비교. 같으면 True."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def create_access_token(
    sub: str,
    claims: dict[str, Any] | None = None,
    expires_in: timedelta | None = None,
) -> str:

    now = datetime.now(UTC)

    exp = now + (expires_in or timedelta(minutes=settings.access_token_expire_minutes))
    payload = {
        **(claims or {}),
        "sub": sub,
        "iat": now,
        "exp": exp,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

def create_refresh_token(
    sub: str,
    expires_in: timedelta | None = None,
) -> str:
    """Refresh 전용 JWT 발급.

    type='refresh' claim 으로 access 와 구분. decode_token(token, 'refresh') 의
    type 가드가 refresh 를 access 자리에 못 쓰도록 막는다.

    access 와 달리 추가 claims 를 받지 않는 이유:
    - refresh 는 신원 재발급 용도이므로 role 등 권한 정보는 access 에만 박는다.
    - 권한이 바뀌어도 access 만료(짧음) 후 새로 발급될 때 즉시 반영된다.
    """
    now = datetime.now(UTC)
    exp = now + (expires_in or timedelta(days=settings.refresh_token_expire_days))
    payload = {
        "sub": sub,
        "iat": now,
        "exp": exp,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except ExpiredSignatureError:
        raise TokenExpiredError() from None
    except JWTError as e:
        raise TokenExpiredError(message="유효하지 않은 토큰") from e

    if payload.get("type") != expected_type:    # refresh 토큰을 access 자리에 못 씀
        raise TokenExpiredError(message=f"토큰 종류 불일치: {payload.get('type')}")
    return payload


# ── 소셜 신규가입 임시 토큰 ─────────────────────────────────
# OAuth 콜백에서 신규 사용자가 감지되면 발급. 사용자가 약관 동의 후 sign-up 호출 시
# 이 토큰을 검증하면 (provider, social_id, email) 가 OAuth PG 로 검증된 값임을 보장.
# 단명 (15분), 1회용은 아님 — 단명 + JWT_SECRET 서명으로 충분.

_SOCIAL_SIGNUP_TOKEN_TYPE = "social-signup"


def create_social_signup_token(
    *,
    provider: str,
    social_id: str,
    email: str | None,
    name: str | None,
    expires_in: timedelta | None = None,
) -> str:
    now = datetime.now(UTC)
    exp = now + (
        expires_in
        or timedelta(minutes=settings.social_signup_token_expire_minutes)
    )
    payload = {
        "provider": provider,
        "social_id": social_id,
        "email": email,
        "name": name,
        "iat": now,
        "exp": exp,
        "type": _SOCIAL_SIGNUP_TOKEN_TYPE,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_social_signup_token(token: str) -> dict[str, Any]:
    """create_social_signup_token 으로 발급한 토큰 검증 + payload 반환."""
    return decode_token(token, expected_type=_SOCIAL_SIGNUP_TOKEN_TYPE)


# ── 이메일 인증 완료 토큰 ─────────────────────────────────────────
# 6자리 코드 검증 성공 시 발급. 회원가입 요청 시 이 토큰으로 이메일 소유를 증명.
# 단명 (15분). 가입 완료 전 소멸하면 코드 재인증 필요.

_EMAIL_VERIFIED_TOKEN_TYPE = "email-verified"


def create_email_verified_token(
    *,
    email: str,
    expires_in: timedelta | None = None,
) -> str:
    now = datetime.now(UTC)
    exp = now + (expires_in or timedelta(minutes=15))
    payload = {
        "email": email,
        "iat": now,
        "exp": exp,
        "type": _EMAIL_VERIFIED_TOKEN_TYPE,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_email_verified_token(token: str) -> dict[str, Any]:
    """create_email_verified_token 으로 발급한 토큰 검증 + payload 반환."""
    return decode_token(token, expected_type=_EMAIL_VERIFIED_TOKEN_TYPE)


# ── 소셜 전용 계정 탈퇴 재인증 토큰 ─────────────────────────────────
# 비밀번호가 없는(has_password=False) 계정이 DELETE /users/me 를 호출하기 전,
# 소셜 로그인을 다시 태워 본인 SocialAccount 와 일치함을 확인하면 발급.
# 단명 (10분) — 탈퇴 확인창에서 바로 이어서 쓰는 용도라 길게 둘 필요 없음.

_WITHDRAWAL_TOKEN_TYPE = "withdrawal"


def create_withdrawal_token(
    *,
    user_id: int,
    expires_in: timedelta | None = None,
) -> str:
    now = datetime.now(UTC)
    exp = now + (expires_in or timedelta(minutes=settings.withdrawal_token_expire_minutes))
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": exp,
        "type": _WITHDRAWAL_TOKEN_TYPE,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_withdrawal_token(token: str) -> dict[str, Any]:
    """create_withdrawal_token 으로 발급한 토큰 검증 + payload 반환."""
    return decode_token(token, expected_type=_WITHDRAWAL_TOKEN_TYPE)
