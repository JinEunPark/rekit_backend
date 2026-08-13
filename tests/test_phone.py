"""app.core.phone 단위 테스트 — 한국 휴대폰 번호 정규화."""

from __future__ import annotations

import pytest

from app.core.phone import normalize_phone


class TestNormalizePhone11Digits:
    def test_digits_only_input_formats_as_3_4_4(self) -> None:
        """하이픈 없는 11자리 입력 → 010-1234-5678 형식으로 변환."""
        assert normalize_phone("01012345678") == "010-1234-5678"

    def test_hyphenated_input_stays_normalized(self) -> None:
        """이미 하이픈이 있는 입력도 동일하게 정규화된다."""
        assert normalize_phone("010-1234-5678") == "010-1234-5678"

    def test_mixed_separators_are_stripped_before_formatting(self) -> None:
        assert normalize_phone("010 1234 5678") == "010-1234-5678"

    def test_016_prefix_accepted(self) -> None:
        assert normalize_phone("01612345678") == "016-1234-5678"


class TestNormalizePhone10Digits:
    def test_10digit_mobile_number_formats_as_3_3_4(self) -> None:
        """구형 10자리 번호(011 등) → 011-123-4567 형식."""
        assert normalize_phone("0111234567") == "011-123-4567"


class TestNormalizePhoneRejects:
    def test_landline_prefix_raises(self) -> None:
        with pytest.raises(ValueError, match="휴대폰"):
            normalize_phone("02-1234-5678")

    def test_too_short_raises(self) -> None:
        with pytest.raises(ValueError, match="휴대폰"):
            normalize_phone("01012")

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(ValueError, match="휴대폰"):
            normalize_phone("010-ABCD-EFGH")

    def test_too_long_raises(self) -> None:
        with pytest.raises(ValueError, match="휴대폰"):
            normalize_phone("010123456789")
