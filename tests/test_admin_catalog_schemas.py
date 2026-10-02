"""admin_catalog 스키마 단위 테스트 — Pydantic 검증.

버그 재현: 프론트가 PATCH /admin/categories/{id} 에 icon/sort_order 를
명시적 null 로 보내면(= NOT NULL 컬럼인데도) 과거에는 그대로 통과해
AdminCategoryResponse 직렬화 단계에서 500 으로 터졌다. 이제는 요청 단계(422)에서 막는다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.catalog.admin_catalog_schemas import AdminCategoryUpdate


def test_update_category_omitting_fields_is_valid() -> None:
    """필드를 아예 안 보내면(기본값 None) 검증을 통과한다 — "미전송" 의미이므로."""
    data = AdminCategoryUpdate()

    assert data.model_dump(exclude_unset=True) == {}


@pytest.mark.parametrize("field", ["title", "icon", "sort_order"])
def test_update_category_explicit_null_on_not_null_field_raises(field: str) -> None:
    """title/icon/sort_order 는 DB NOT NULL — 명시적 null 전송은 422 로 거부된다."""
    with pytest.raises(ValidationError):
        AdminCategoryUpdate.model_validate({field: None})


def test_update_category_explicit_null_image_url_is_valid() -> None:
    """image_url 은 nullable — null 을 명시적으로 보내면 이미지 제거 의도로 허용된다."""
    data = AdminCategoryUpdate.model_validate({"image_url": None})

    assert data.model_dump(exclude_unset=True) == {"image_url": None}


def test_update_category_valid_values_pass_through() -> None:
    data = AdminCategoryUpdate(title="TV", icon="📺", sort_order=0)

    assert data.model_dump(exclude_unset=True) == {
        "title": "TV",
        "icon": "📺",
        "sort_order": 0,
    }
