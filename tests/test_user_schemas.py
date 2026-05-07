"""user 모듈 Pydantic 스키마 검증.

ChangePasswordRequest:
- camelCase alias 매핑 (currentPassword → current_password)
- newPassword 정책 (영문+숫자, 8자 이상) — auth_schemas 의 validate_password_policy 재사용
- currentPassword 는 길이 1+ 만 통과 (정책 적용 X — 기존 비번이 정책 위반일 수도)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.user.user_schemas import ChangePasswordRequest


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
