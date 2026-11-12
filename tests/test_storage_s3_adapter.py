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


def test_client_config_computes_checksum_only_when_required() -> None:
    """SeaweedFS 는 botocore 1.36+ 기본값(aws-chunked + CRC 트레일러) PutObject 를
    InvalidAccessKeyId 로 거부한다 (운영 2026-11-13 재현). 필요할 때만 체크섬을 붙여야 한다."""
    config = S3StorageAdapter.client_config(force_path_style=True)

    assert config.request_checksum_calculation == "when_required"
    assert config.response_checksum_validation == "when_required"


@pytest.mark.parametrize(("force_path_style", "style"), [(True, "path"), (False, "auto")])
def test_client_config_addressing_style_follows_setting(
    force_path_style: bool, style: str
) -> None:
    config = S3StorageAdapter.client_config(force_path_style=force_path_style)

    assert config.s3 == {"addressing_style": style}
    assert config.signature_version == "s3v4"
