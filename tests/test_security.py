"""security 모듈 단위 테스트.

User 모델 / DB / Redis 의존 없음 — 순수 함수만 검증.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.exceptions import TokenExpiredError
from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)

# ── 비밀번호 해시 ──────────────────────────────────────────


def test_password_hash_is_not_plain() -> None:
    hashed = hash_password("mysecretpassword")
    assert hashed != "mysecretpassword"
    assert hashed.startswith("$2b$")  # bcrypt 식별자


def test_password_verify_accepts_correct_password() -> None:
    hashed = hash_password("mysecretpassword")
    assert verify_password("mysecretpassword", hashed) is True


def test_password_verify_rejects_wrong_password() -> None:
    hashed = hash_password("mysecretpassword")
    assert verify_password("wrongpassword", hashed) is False


def test_password_hash_is_unique_per_call() -> None:
    """같은 비번도 매번 다른 해시 — bcrypt 가 매번 새 salt 생성하기 때문."""
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2
    # 그래도 둘 다 검증은 통과해야 함
    assert verify_password("same", h1)
    assert verify_password("same", h2)


# ── JWT 발급 / 검증 ───────────────────────────────────────


def test_access_token_roundtrip() -> None:
    """sub 과 추가 claims 가 토큰을 거쳐도 보존되는가."""
    token = create_access_token(sub="42", claims={"role": "USER"})
    payload = decode_token(token)
    assert payload["sub"] == "42"
    assert payload["role"] == "USER"
    assert payload["type"] == "access"


def test_access_token_includes_iat_and_exp() -> None:
    token = create_access_token(sub="42", claims={})
    payload = decode_token(token)
    assert "iat" in payload
    assert "exp" in payload
    assert payload["exp"] > payload["iat"]


def test_access_token_iat_is_utc_aware() -> None:
    """iat 가 UTC timestamp 인지 확인 — 서버 TZ 와 무관해야 함."""
    token = create_access_token(sub="42", claims={})
    payload = decode_token(token)
    iat = datetime.fromtimestamp(payload["iat"], tz=UTC)
    delta = abs((datetime.now(UTC) - iat).total_seconds())
    assert delta < 5  # 발급 직후라 5초 이내여야 정상


def test_access_token_default_expires_in_30_minutes() -> None:
    """settings 기본값(30분) 검증."""
    token = create_access_token(sub="42", claims={})
    payload = decode_token(token)
    expected_exp = payload["iat"] + 30 * 60
    assert abs(payload["exp"] - expected_exp) < 5


# ── 만료 / 위변조 ─────────────────────────────────────────


def test_expired_token_raises_token_expired() -> None:
    token = create_access_token(
        sub="42", claims={}, expires_in=timedelta(seconds=-10)
    )
    with pytest.raises(TokenExpiredError):
        decode_token(token)


def test_tampered_signature_raises() -> None:
    """JWT 끝 3자(서명 일부) 변조 시 거부."""
    token = create_access_token(sub="42", claims={})
    tampered = token[:-3] + "XXX"
    with pytest.raises(TokenExpiredError):
        decode_token(tampered)


def test_garbage_token_raises() -> None:
    """JWT 형식이 아예 아닌 문자열도 안전하게 거부."""
    with pytest.raises(TokenExpiredError):
        decode_token("not.a.jwt")


# ── 함수 계약 — sub/exp/type 덮어쓰기 방지 ─────────────────
# 이 테스트들은 미래에 누가 dict 합치는 순서를 잘못 바꿔도 시스템 필드가
# 보호되도록 함수의 계약을 코드로 박아두는 안전망이다 (defense in depth).


def test_create_token_user_cannot_override_sub() -> None:
    token = create_access_token(
        sub="42",
        claims={"sub": "1", "role": "ADMIN"},  # 공격 시도
    )
    payload = decode_token(token)
    assert payload["sub"] == "42"  # 시스템 값 보존
    assert payload["role"] == "ADMIN"  # 정상 추가는 됨


def test_create_token_user_cannot_override_exp() -> None:
    """claims 로 exp 를 무한대로 늘리려 해도 시스템 exp 가 우선."""
    far_future = int(datetime.now(UTC).timestamp()) + 10**9
    token = create_access_token(
        sub="42",
        claims={"exp": far_future},
    )
    payload = decode_token(token)
    assert payload["exp"] - payload["iat"] < 60 * 60  # 1시간 미만


def test_create_token_user_cannot_override_type() -> None:
    token = create_access_token(
        sub="42",
        claims={"type": "refresh"},
    )
    payload = decode_token(token)
    assert payload["type"] == "access"


# ── decode_token 의 type 가드 ────────────────────────────


def test_decode_token_rejects_wrong_type() -> None:
    """expected_type 이 다르면 거부 — refresh 토큰을 access 자리에 못 씀."""
    token = create_access_token(sub="42", claims={})
    with pytest.raises(TokenExpiredError):
        decode_token(token, expected_type="refresh")
