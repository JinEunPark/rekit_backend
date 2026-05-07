"""Validation 응답 포맷 테스트.

api.md §1.3 — 검증 실패도 비즈니스 에러와 같은 wrapper:
    { "error": { "code": "VALIDATION_ERROR", "message": "...", "fields": {...} } }

`fields` 는 `{field_name: 사용자에게 그대로 보여줄 한국어 메시지}`. 클라는
`error.fields.password` 한 줄로 폼 에러를 표시할 수 있다.
"""

from __future__ import annotations

from fastapi import Body, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, field_validator

from app.core.exceptions import register_exception_handlers


class _PasswordBody(BaseModel):
    password: str = Field(min_length=8)

    @field_validator("password")
    @classmethod
    def _must_have_digit(cls, v: str) -> str:
        if not any(c.isdigit() for c in v):
            raise ValueError("비밀번호는 숫자를 포함해야 합니다.")
        return v


def _build_client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/echo")
    async def _echo(body: _PasswordBody = Body()) -> dict[str, bool]:
        del body
        return {"ok": True}

    return TestClient(app)


def test_validation_response_uses_business_wrapper() -> None:
    """422 응답도 {error: {code, message, fields}} wrapper 를 따른다."""
    # Arrange
    client = _build_client()

    # Act
    res = client.post("/echo", json={"password": "abcdefgh"})

    # Assert
    assert res.status_code == 422
    body = res.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert isinstance(body["error"]["message"], str)
    assert "fields" in body["error"]


def test_validation_field_value_is_korean_message_for_value_error() -> None:
    """field_validator 의 ValueError 메시지가 그대로 fields[name] 에 들어간다."""
    # Arrange
    client = _build_client()

    # Act
    res = client.post("/echo", json={"password": "abcdefgh"})

    # Assert
    assert res.json()["error"]["fields"]["password"] == "비밀번호는 숫자를 포함해야 합니다."


def test_validation_strips_value_error_prefix() -> None:
    """Pydantic 의 'Value error, ' 접두어는 제거된다."""
    # Arrange
    client = _build_client()

    # Act
    res = client.post("/echo", json={"password": "abcdefgh"})

    # Assert
    msg = res.json()["error"]["fields"]["password"]
    assert not msg.lower().startswith("value error")


def test_validation_missing_field_has_message() -> None:
    """필수 필드 누락도 같은 형식으로 내려간다 (메시지는 Pydantic 기본)."""
    # Arrange
    client = _build_client()

    # Act
    res = client.post("/echo", json={})

    # Assert
    fields = res.json()["error"]["fields"]
    assert "password" in fields
    assert isinstance(fields["password"], str)
    assert fields["password"]  # 빈 문자열 아님
