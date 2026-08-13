"""한국 휴대폰 번호 정규화 — 저장 형식은 항상 010-0000-0000 (하이픈 포함).

`PhoneStr`/`OptionalPhoneStr` 은 Pydantic 스키마의 phone 필드에 그대로 붙여
쓰는 타입 별칭 — 매 스키마마다 반복되던 `@field_validator` 보일러플레이트를
없앤다.
"""

import re
from typing import Annotated

from pydantic import AfterValidator

_PHONE_DIGITS_RE = re.compile(r"^01[016789]\d{7,8}$")


def normalize_phone(raw: str) -> str:
    """구분자(하이픈/공백) 유무와 무관하게 입력받아 010-0000-0000 형식으로 반환한다.

    11자리(010-0000-0000)와 구형 10자리(011-000-0000) 번호를 모두 지원.
    """
    digits = re.sub(r"[\s-]", "", raw)
    if not _PHONE_DIGITS_RE.match(digits):
        raise ValueError("올바른 휴대폰 번호를 입력해주세요. (예: 010-1234-5678)")
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def _normalize_optional_phone(raw: str | None) -> str | None:
    return normalize_phone(raw) if raw is not None else raw


PhoneStr = Annotated[str, AfterValidator(normalize_phone)]
OptionalPhoneStr = Annotated[str | None, AfterValidator(_normalize_optional_phone)]
