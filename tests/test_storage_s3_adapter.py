"""S3StorageAdapter 키 생성 단위 테스트.

presigned URL 발급 자체는 외부 S3 호출이 필요해 통합 테스트 영역이지만,
오브젝트 키 생성(순수 함수)은 단위 테스트로 충분히 커버 가능하다.

- generate_product_image_key: products/ prefix
- generate_category_image_key: categories/ prefix (카테고리 이미지 업로드용 신규 로직)
"""

from __future__ import annotations

import pytest

from app.common.storage.s3_adapter import S3StorageAdapter


@pytest.mark.parametrize(
    ("content_type", "ext"),
    [("image/jpeg", "jpg"), ("image/png", "png"), ("image/webp", "webp")],
)
def test_generate_category_image_key_uses_categories_prefix(
    content_type: str, ext: str
) -> None:
    key = S3StorageAdapter.generate_category_image_key(content_type)

    assert key.startswith("categories/")
    assert key.endswith(f".{ext}")


def test_generate_category_image_key_is_unique_per_call() -> None:
    first = S3StorageAdapter.generate_category_image_key("image/png")
    second = S3StorageAdapter.generate_category_image_key("image/png")

    assert first != second


def test_generate_product_image_key_uses_products_prefix() -> None:
    key = S3StorageAdapter.generate_product_image_key("image/jpeg")

    assert key.startswith("products/")
