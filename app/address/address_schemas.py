"""address 모듈 Pydantic 스키마 (DTO).

내부 필드 snake_case, JSON 응답 camelCase alias (api.md §1.3 응답 포맷).
한국 우편번호 5자리, 한국 휴대폰 번호 형식을 검증한다.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_PHONE_RE = re.compile(r"^01[016789]\d{7,8}$")
_ZIPCODE_RE = re.compile(r"^\d{5}$")
_LABEL_MAX = 30
_MEMO_MAX = 200


def _clean_phone(v: str) -> str:
    """하이픈/공백 제거 후 한국 휴대폰 번호 형식 검증. 정규화된 숫자만 반환."""
    clean = v.replace("-", "").replace(" ", "")
    if not _PHONE_RE.match(clean):
        raise ValueError("올바른 휴대폰 번호를 입력해주세요. (예: 010-1234-5678)")
    return clean


def _check_zipcode(v: str) -> str:
    if not _ZIPCODE_RE.match(v):
        raise ValueError("우편번호는 5자리 숫자여야 합니다.")
    return v


class AddressCreate(BaseModel):
    """POST /addresses 요청 바디."""

    model_config = ConfigDict(populate_by_name=True)

    recipient: str = Field(min_length=1, max_length=50, description="수령인 이름")
    phone: str = Field(description="수령인 연락처 (하이픈 허용, 저장 시 정규화)")
    zipcode: str = Field(description="우편번호 5자리")
    address1: str = Field(min_length=1, max_length=255, description="기본 주소 (도로명/지번)")
    address2: str | None = Field(default=None, max_length=255, description="상세 주소 (동·호수)")
    label: str | None = Field(
        default=None, max_length=_LABEL_MAX, description="배송지 별칭 (예: 집, 회사)"
    )
    memo: str | None = Field(default=None, max_length=_MEMO_MAX, description="배송 메모")
    is_default: bool = Field(default=False, description="기본 배송지 여부")

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return _clean_phone(v)

    @field_validator("zipcode")
    @classmethod
    def _zipcode(cls, v: str) -> str:
        return _check_zipcode(v)


class AddressUpdate(BaseModel):
    """PATCH /addresses/{id} 요청 바디 — 모든 필드 선택적.

    보내지 않은 필드는 exclude_unset=True 로 걸러져 기존 값이 유지된다.
    address2=null 을 명시적으로 보내면 상세 주소가 지워진다.
    """

    model_config = ConfigDict(populate_by_name=True)

    recipient: str | None = Field(default=None, min_length=1, max_length=50)
    phone: str | None = Field(default=None)
    zipcode: str | None = Field(default=None)
    address1: str | None = Field(default=None, min_length=1, max_length=255)
    address2: str | None = Field(default=None)
    label: str | None = Field(default=None, max_length=_LABEL_MAX)
    memo: str | None = Field(default=None, max_length=_MEMO_MAX)
    is_default: bool | None = Field(default=None)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return _clean_phone(v) if v is not None else v

    @field_validator("zipcode")
    @classmethod
    def _zipcode(cls, v: str | None) -> str | None:
        return _check_zipcode(v) if v is not None else v


class AddressResponse(BaseModel):
    """배송지 응답 DTO. from_attributes=True 로 ORM 객체에서 직접 매핑된다."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    recipient: str
    phone: str
    zipcode: str
    address1: str
    address2: str | None
    label: str | None
    memo: str | None
    is_default: bool = Field(serialization_alias="isDefault")
