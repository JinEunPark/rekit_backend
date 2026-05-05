
from datetime import UTC, datetime, timedelta, timezone
import bcrypt
from jose import ExpiredSignatureError, JWTError, jwt
from app.core.config import settings
from app.core.exceptions import TokenExpired


def hash_password(plain: str) -> str:
    """bcrypt 해시. 결과는 60자 고정, '$2b$12$...' 형식."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """저장된 해시와 평문 비교. 같으면 True."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def create_access_token(
    sub: str,
    claims: dict | None = None,
    expires_in: timedelta | None = None,
) -> str:

    now = datetime.now(timezone.utc)

    exp = now + (expires_in or timedelta(minutes=settings.access_token_expire_minutes))
    payload = {
        **(claims or {}),
        "sub": sub,
        "iat": now,
        "exp": exp,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except ExpiredSignatureError:
        raise TokenExpired() from None
    except JWTError as e:
        raise TokenExpired(message="유효하지 않은 토큰") from e

    if payload.get("type") != expected_type:    # refresh 토큰을 access 자리에 못 씀
        raise TokenExpired(message=f"토큰 종류 불일치: {payload.get('type')}")
    return payload
