"""auth schemas 단위 테스트.

라우터/DB 없이 Pydantic 모델만 검증한다. 라우터에서 막히는 입력은 schema 단위에서
모두 잡히므로, 통합 테스트로 같은 케이스를 다시 짤 필요가 없다.

참고: tests/test_pagination.py — DTO 단위 테스트의 표본.
"""

import pytest
from pydantic import ValidationError

from app.auth.auth_schemas import (
    CheckLoginIdRequest,
    SignInRequest,
    SignUpRequest,
    TokenResponse,
    UserResponse,
)

# ── SignInRequest ─────────────────────────────────────


def test_sign_in_request_rejects_empty_login_id() -> None:
    with pytest.raises(ValidationError):
        SignInRequest(login_id="", password="pw")


def test_sign_in_request_rejects_empty_password() -> None:
    with pytest.raises(ValidationError):
        SignInRequest(login_id="abcd", password="")


def test_sign_in_request_accepts_camel_case_login_id() -> None:
    """클라가 camelCase 로 보내는 loginId 키도 받는다 (validation_alias)."""
    req = SignInRequest.model_validate({"loginId": "eunyoung_kim", "password": "pw"})
    assert req.login_id == "eunyoung_kim"


def test_sign_in_request_remember_defaults_to_false() -> None:
    req = SignInRequest(login_id="abcd", password="pw")
    assert req.remember is False


# ── SignUpRequest ─────────────────────────────────────


def _valid_sign_up_payload(**overrides: object) -> dict[str, object]:
    """기본 정상 페이로드. 필요 필드만 override 해서 케이스 빌드."""
    base: dict[str, object] = {
        "loginId": "eunyoung_kim",
        "username": "박은영",
        "password": "abc12345",
        "email": "user@example.com",
        "agreedTerms": True,
        "agreedPrivacy": True,
        "agreedMarketing": False,
    }
    base.update(overrides)
    return base


def test_sign_up_request_accepts_valid_payload() -> None:
    req = SignUpRequest.model_validate(_valid_sign_up_payload())
    assert req.login_id == "eunyoung_kim"
    assert req.username == "박은영"
    assert req.email == "user@example.com"


def test_sign_up_request_normalizes_email_to_lowercase() -> None:
    req = SignUpRequest.model_validate(_valid_sign_up_payload(email="A@B.COM"))
    assert req.email == "a@b.com"


def test_sign_up_request_rejects_invalid_login_id_pattern() -> None:
    """한글/특수문자/3자 이하 모두 거부."""
    with pytest.raises(ValidationError):
        SignUpRequest.model_validate(_valid_sign_up_payload(loginId="abc"))


def test_sign_up_request_rejects_short_password() -> None:
    with pytest.raises(ValidationError):
        SignUpRequest.model_validate(_valid_sign_up_payload(password="ab12"))


def test_sign_up_request_rejects_password_without_digit() -> None:
    """영문만 → 거부 (영문+숫자 동시 포함 강제)."""
    with pytest.raises(ValidationError):
        SignUpRequest.model_validate(_valid_sign_up_payload(password="abcdefgh"))


def test_sign_up_request_rejects_password_without_letter() -> None:
    with pytest.raises(ValidationError):
        SignUpRequest.model_validate(_valid_sign_up_payload(password="12345678"))


def test_sign_up_request_rejects_when_required_terms_false() -> None:
    """필수 약관 미동의 → ValidationError → 라우터에서 422."""
    with pytest.raises(ValidationError):
        SignUpRequest.model_validate(_valid_sign_up_payload(agreedTerms=False))


def test_sign_up_request_rejects_when_required_privacy_false() -> None:
    with pytest.raises(ValidationError):
        SignUpRequest.model_validate(_valid_sign_up_payload(agreedPrivacy=False))


def test_sign_up_request_rejects_empty_username() -> None:
    """이름은 1자 이상 필수."""
    with pytest.raises(ValidationError):
        SignUpRequest.model_validate(_valid_sign_up_payload(username=""))


# ── CheckLoginIdRequest ───────────────────────────────


def test_check_login_id_request_rejects_short_id() -> None:
    with pytest.raises(ValidationError):
        CheckLoginIdRequest.model_validate({"loginId": "abc"})


def test_check_login_id_request_accepts_valid_id() -> None:
    req = CheckLoginIdRequest.model_validate({"loginId": "eunyoung_kim"})
    assert req.login_id == "eunyoung_kim"


# ── 응답 직렬화 (camelCase) ───────────────────────────


def test_token_response_serializes_with_camel_case_alias() -> None:
    resp = TokenResponse(access_token="abc")
    dumped = resp.model_dump(by_alias=True)
    assert dumped == {
        "accessToken": "abc",
        "tokenType": "bearer",
        "mustChangePassword": False,
    }


def test_token_response_serializes_must_change_password_when_true() -> None:
    """임시 비번 사용 중인 사용자 로그인 시 mustChangePassword=True 직렬화."""
    resp = TokenResponse(access_token="abc", must_change_password=True)
    dumped = resp.model_dump(by_alias=True)
    assert dumped["mustChangePassword"] is True


def test_user_response_serializes_login_id_and_eco_kg_as_camel_case() -> None:
    """login_id → loginId, eco_kg → ecoKg 직렬화."""
    resp = UserResponse(
        id=1,
        login_id="eunyoung_kim",
        username="박은영",
        email="a@b.com",
        verified=False,
    )
    dumped = resp.model_dump(by_alias=True)
    assert dumped["loginId"] == "eunyoung_kim"
    assert dumped["username"] == "박은영"
    assert dumped["ecoKg"] == 0
