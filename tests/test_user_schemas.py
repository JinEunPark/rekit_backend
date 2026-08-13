"""user 모듈 Pydantic 스키마 검증.

ChangePasswordRequest:
- camelCase alias 매핑 (currentPassword → current_password)
- newPassword 정책 (영문+숫자, 8자 이상) — auth_schemas 의 validate_password_policy 재사용
- currentPassword 는 길이 1+ 만 통과 (정책 적용 X — 기존 비번이 정책 위반일 수도)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.user.user_schemas import (
    ChangePasswordRequest,
    PhoneSendRequest,
    PhoneVerifyRequest,
    UpdateProfileRequest,
)


def test_change_password_request_accepts_camelcase_alias() -> None:
    # Arrange / Act
    req = ChangePasswordRequest(
        **{"currentPassword": "abc12345", "newPassword": "new99zzz"}  # type: ignore[arg-type]
    )

    # Assert
    assert req.current_password == "abc12345"
    assert req.new_password == "new99zzz"


def test_change_password_request_rejects_new_password_too_short() -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValidationError):
        ChangePasswordRequest(
            **{"currentPassword": "abc12345", "newPassword": "ab12"}  # type: ignore[arg-type]
        )


def test_change_password_request_rejects_new_password_without_digit() -> None:
    """정책: 영문+숫자 동시 포함."""
    # Arrange / Act / Assert
    with pytest.raises(ValidationError):
        ChangePasswordRequest(
            **{"currentPassword": "abc12345", "newPassword": "alphabetonly"}  # type: ignore[arg-type]
        )


def test_change_password_request_rejects_new_password_without_letter() -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValidationError):
        ChangePasswordRequest(
            **{"currentPassword": "abc12345", "newPassword": "12345678"}  # type: ignore[arg-type]
        )


def test_change_password_request_rejects_empty_current_password() -> None:
    """현재 비번이 빈 문자열이면 바로 거부 (verify 호출 전에)."""
    # Arrange / Act / Assert
    with pytest.raises(ValidationError):
        ChangePasswordRequest(
            **{"currentPassword": "", "newPassword": "new99zzz"}  # type: ignore[arg-type]
        )


# ── phone 정규화 (010-0000-0000 형식 저장) ─────────────────────────────────────


def test_update_profile_request_normalizes_phone_to_hyphenated_format() -> None:
    req = UpdateProfileRequest(phone="01012345678")
    assert req.phone == "010-1234-5678"


def test_update_profile_request_none_phone_stays_none() -> None:
    """phone 미전송(None) 은 정규화 대상이 아니다 — partial update 시 그대로 유지."""
    req = UpdateProfileRequest(username="새이름")
    assert req.phone is None


def test_update_profile_request_rejects_invalid_phone() -> None:
    with pytest.raises(ValidationError):
        UpdateProfileRequest(phone="02-1234-5678")


def test_phone_send_request_normalizes_hyphenated_input() -> None:
    req = PhoneSendRequest(phone="010-1234-5678")
    assert req.phone == "010-1234-5678"


def test_phone_send_request_normalizes_digit_only_input() -> None:
    req = PhoneSendRequest(phone="01012345678")
    assert req.phone == "010-1234-5678"


def test_phone_send_request_rejects_invalid_phone() -> None:
    with pytest.raises(ValidationError):
        PhoneSendRequest(phone="not-a-phone")


def test_phone_verify_request_normalizes_digit_only_input() -> None:
    req = PhoneVerifyRequest(phone="01012345678")
    assert req.phone == "010-1234-5678"
