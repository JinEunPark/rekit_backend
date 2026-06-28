"""address 스키마 단위 테스트 — Pydantic 검증."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.address.address_schemas import AddressCreate, AddressResponse, AddressUpdate

# ── 공용 valid payload ─────────────────────────────────

_VALID: dict[str, Any] = dict(
    recipient="홍길동",
    phone="01012345678",
    zipcode="12345",
    address1="서울시 강남구 테헤란로 1",
)


# ── AddressCreate: 전화번호 검증 ───────────────────────


class TestAddressCreatePhone:
    def test_phone_with_hyphens_normalizes_to_digits(self) -> None:
        """하이픈 포함 입력 → 숫자만 저장."""
        data = AddressCreate(**{**_VALID, "phone": "010-1234-5678"})
        assert data.phone == "01012345678"

    def test_phone_016_prefix_accepted(self) -> None:
        data = AddressCreate(**{**_VALID, "phone": "01612345678"})
        assert data.phone == "01612345678"

    def test_landline_number_raises(self) -> None:
        """유선전화(02, 031 등)는 거부."""
        with pytest.raises(ValidationError) as exc:
            AddressCreate(**{**_VALID, "phone": "02-1234-5678"})
        assert "phone" in str(exc.value)

    def test_too_short_number_raises(self) -> None:
        with pytest.raises(ValidationError):
            AddressCreate(**{**_VALID, "phone": "01012"})

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(ValidationError):
            AddressCreate(**{**_VALID, "phone": "010-ABCD-EFGH"})


# ── AddressCreate: 우편번호 검증 ───────────────────────


class TestAddressCreateZipcode:
    def test_valid_5digit_zipcode(self) -> None:
        data = AddressCreate(**_VALID)
        assert data.zipcode == "12345"

    def test_4digit_zipcode_raises(self) -> None:
        with pytest.raises(ValidationError) as exc:
            AddressCreate(**{**_VALID, "zipcode": "1234"})
        assert "zipcode" in str(exc.value)

    def test_6digit_zipcode_raises(self) -> None:
        with pytest.raises(ValidationError):
            AddressCreate(**{**_VALID, "zipcode": "123456"})

    def test_zipcode_with_letter_raises(self) -> None:
        with pytest.raises(ValidationError):
            AddressCreate(**{**_VALID, "zipcode": "1234A"})


# ── AddressCreate: 기본값 및 선택 필드 ────────────────


class TestAddressCreateDefaults:
    def test_is_default_defaults_to_false(self) -> None:
        data = AddressCreate(**_VALID)
        assert data.is_default is False

    def test_address2_defaults_to_none(self) -> None:
        data = AddressCreate(**_VALID)
        assert data.address2 is None

    def test_address2_can_be_set(self) -> None:
        data = AddressCreate(**{**_VALID, "address2": "101동 202호"})
        assert data.address2 == "101동 202호"

    def test_recipient_max_length_exceeded_raises(self) -> None:
        with pytest.raises(ValidationError):
            AddressCreate(**{**_VALID, "recipient": "가" * 51})

    def test_address1_empty_raises(self) -> None:
        with pytest.raises(ValidationError):
            AddressCreate(**{**_VALID, "address1": ""})


# ── AddressUpdate: 선택적 부분 수정 ───────────────────


class TestAddressUpdate:
    def test_all_fields_optional(self) -> None:
        data = AddressUpdate()
        assert data.recipient is None
        assert data.phone is None
        assert data.is_default is None

    def test_partial_update_only_phone(self) -> None:
        data = AddressUpdate(phone="01099998888")
        assert data.phone == "01099998888"
        assert data.recipient is None

    def test_phone_validation_applies_in_update(self) -> None:
        with pytest.raises(ValidationError):
            AddressUpdate(phone="02-invalid")

    def test_zipcode_validation_applies_in_update(self) -> None:
        with pytest.raises(ValidationError):
            AddressUpdate(zipcode="9999")

    def test_unset_fields_excluded_from_model_dump(self) -> None:
        """exclude_unset=True 시 명시하지 않은 필드는 포함되지 않는다."""
        data = AddressUpdate(phone="01099998888")
        dumped = data.model_dump(exclude_unset=True)
        assert "phone" in dumped
        assert "recipient" not in dumped

    def test_explicit_none_included_in_model_dump(self) -> None:
        """address2=None 명시 → exclude_unset 시에도 포함돼야 한다 (상세 주소 삭제 의도)."""
        data = AddressUpdate.model_validate({"address2": None})
        dumped = data.model_dump(exclude_unset=True)
        assert "address2" in dumped
        assert dumped["address2"] is None


# ── AddressResponse: ORM → DTO 매핑 ───────────────────


def _fake_address(
    *,
    id: int = 1,
    recipient: str = "홍",
    phone: str = "01012345678",
    zipcode: str = "12345",
    address1: str = "서울",
    address2: str | None = None,
    label: str | None = None,
    memo: str | None = None,
    is_default: bool = False,
) -> object:
    """AddressResponse.model_validate 용 ORM 속성 스텁."""

    class _Fake:
        pass

    obj = _Fake()
    for k, v in locals().items():
        if k != "obj":
            setattr(obj, k, v)
    return obj


class TestAddressResponse:
    def test_from_attributes_maps_correctly(self) -> None:
        resp = AddressResponse.model_validate(
            _fake_address(id=7, recipient="김철수", phone="01011112222",
                          zipcode="54321", address1="부산시 해운대구",
                          address2="301호", label="집", is_default=True)
        )
        assert resp.id == 7
        assert resp.is_default is True

    def test_serialization_alias_is_default(self) -> None:
        """is_default → isDefault 로 직렬화되어야 한다."""
        resp = AddressResponse.model_validate(_fake_address())
        dumped = resp.model_dump(by_alias=True)
        assert "isDefault" in dumped
        assert "is_default" not in dumped
