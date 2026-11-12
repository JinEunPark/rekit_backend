"""catalog_utils.thumbnail_url — 카드용 썸네일 선택 규칙.

카드(약 200px)에 1600px 상세 이미지를 내려보내지 않도록 대표 이미지의 thumb_url 을 우선 쓰고,
썸네일이 없는 기존 이미지는 원본 url 로 폴백한다.
"""

from __future__ import annotations

from app.catalog.catalog_utils import thumbnail_url
from app.catalog.models import ConditionGrade, Product, ProductImage, ProductStatus


def _product(images: list[ProductImage]) -> Product:
    p = Product(
        title="테스트",
        description="",
        category="REFRIGERATOR",
        condition_grade=ConditionGrade.A,
        warranty_works=True,
        price=1000,
        stock=1,
        status=ProductStatus.ACTIVE,
    )
    p.images = images
    return p


def test_thumbnail_url_returns_none_when_no_images() -> None:
    assert thumbnail_url(_product([])) is None


def test_thumbnail_url_falls_back_to_url_when_thumb_missing() -> None:
    img = ProductImage(url="https://cdn/a.jpg", sort_order=0, thumb_url=None)

    assert thumbnail_url(_product([img])) == "https://cdn/a.jpg"


def test_thumbnail_url_prefers_thumb_url_of_first_image() -> None:
    first = ProductImage(url="https://cdn/a.webp", sort_order=0, thumb_url="https://cdn/a_t.webp")
    second = ProductImage(url="https://cdn/b.webp", sort_order=1, thumb_url="https://cdn/b_t.webp")

    assert thumbnail_url(_product([first, second])) == "https://cdn/a_t.webp"
