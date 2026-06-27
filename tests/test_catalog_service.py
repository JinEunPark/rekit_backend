"""catalog service 단위 테스트.

DB 없이 fake repo + in-memory Product 객체로 도메인 로직 검증.
- 필터 (카테고리/등급/가격/동작보증/키워드)
- 정렬 (최신/낮은가격/높은가격)
- 페이지네이션 meta 계산
- thumbnail_url: images[0].url, 이미지 없으면 None
- discount_pct: original_price 기반 계산, 없으면 None
- get_product: 상세 + 이미지 목록
- ProductNotFound: 없는 상품 조회 시 raise
- get_featured: ACTIVE 최신 N건
- get_categories: DB 기반 동적 카테고리, sort_order 순
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.catalog.catalog_schemas import ProductListParams, ProductSort
from app.catalog.catalog_service import CatalogService
from app.catalog.models import (
    ConditionGrade,
    Product,
    ProductCategoryMetaItem,
    ProductImage,
    ProductStatus,
)
from app.core.exceptions import ProductNotFound

# ── 팩토리 ──────────────────────────────────────────────────


def make_product(
    *,
    product_id: int = 1,
    title: str = "테스트 냉장고",
    category: str = "REFRIGERATOR",
    brand: str | None = "삼성",
    model_name: str | None = "RT38K",
    condition_grade: ConditionGrade = ConditionGrade.A,
    warranty_works: bool = True,
    price: int = 300_000,
    original_price: int | None = 500_000,
    stock: int = 1,
    status: ProductStatus = ProductStatus.ACTIVE,
    images: list[ProductImage] | None = None,
) -> Product:
    p = Product(
        title=title,
        description="상세 설명",
        category=category,
        brand=brand,
        model_name=model_name,
        condition_grade=condition_grade,
        warranty_works=warranty_works,
        price=price,
        original_price=original_price,
        stock=stock,
        status=status,
    )
    p.id = product_id
    p.created_at = datetime.now(UTC)
    for img in images or []:
        p.images.append(img)
    return p


def make_image(
    *,
    image_id: int = 1,
    url: str = "https://cdn.example.com/img.jpg",
    sort_order: int = 0,
    label: str | None = "정면",
) -> ProductImage:
    img = ProductImage(url=url, sort_order=sort_order, label=label)
    img.id = image_id
    return img


def make_category(
    *,
    category_id: str = "REFRIGERATOR",
    title: str = "냉장고",
    icon: str = "fridge",
    sort_order: int = 1,
) -> ProductCategoryMetaItem:
    c = ProductCategoryMetaItem(id=category_id, title=title, icon=icon, sort_order=sort_order)
    return c


# ── Fake repo ────────────────────────────────────────────────


class _FakeCatalogRepo:
    """Python 리스트 기반 — SQL 없이 필터·정렬·페이지네이션 재현."""

    def __init__(
        self,
        products: list[Product],
        categories: list[ProductCategoryMetaItem] | None = None,
    ) -> None:
        self._products = products
        self._categories = categories or []

    async def get_list(self, params: ProductListParams) -> tuple[list[Product], int]:
        items = [p for p in self._products if p.status == ProductStatus.ACTIVE]

        if params.category is not None:
            items = [p for p in items if p.category == params.category]
        if params.grade is not None:
            items = [p for p in items if p.condition_grade == params.grade]
        if params.min_price is not None:
            items = [p for p in items if p.price >= params.min_price]
        if params.max_price is not None:
            items = [p for p in items if p.price <= params.max_price]
        if params.warranty is not None:
            items = [p for p in items if p.warranty_works == params.warranty]
        if params.q:
            q = params.q.lower()
            items = [
                p
                for p in items
                if q in (p.title or "").lower()
                or q in (p.brand or "").lower()
                or q in (p.model_name or "").lower()
            ]

        total = len(items)

        if params.sort == ProductSort.PRICE_ASC:
            items = sorted(items, key=lambda p: p.price)
        elif params.sort == ProductSort.PRICE_DESC:
            items = sorted(items, key=lambda p: p.price, reverse=True)
        else:
            items = sorted(items, key=lambda p: p.id, reverse=True)  # type: ignore[arg-type]

        start = (params.page - 1) * params.size
        return items[start : start + params.size], total

    async def get_by_id(self, product_id: int) -> Product | None:
        return next((p for p in self._products if p.id == product_id), None)

    async def get_featured(self, limit: int = 4) -> list[Product]:
        active = [p for p in self._products if p.status == ProductStatus.ACTIVE]
        return sorted(active, key=lambda p: p.id, reverse=True)[:limit]  # type: ignore[arg-type]

    async def get_by_ids(self, product_ids: list[int]) -> list[Product]:
        return [p for p in self._products if p.id in product_ids]

    async def get_categories(self) -> list[ProductCategoryMetaItem]:
        return sorted(self._categories, key=lambda c: c.sort_order)


def _make_service(
    products: list[Product],
    categories: list[ProductCategoryMetaItem] | None = None,
) -> CatalogService:
    return CatalogService(_FakeCatalogRepo(products, categories))  # type: ignore[arg-type]


# ── list_products ────────────────────────────────────────────


async def test_list_products_empty() -> None:
    service = _make_service([])

    result = await service.list_products(ProductListParams())

    assert result.items == []
    assert result.meta.total == 0
    assert result.meta.total_pages == 0


async def test_list_products_excludes_inactive_and_soldout() -> None:
    """ACTIVE 상품만 반환 — INACTIVE·SOLD_OUT 제외."""
    products = [
        make_product(product_id=1, status=ProductStatus.ACTIVE),
        make_product(product_id=2, status=ProductStatus.INACTIVE),
        make_product(product_id=3, status=ProductStatus.SOLD_OUT),
    ]
    service = _make_service(products)

    result = await service.list_products(ProductListParams())

    assert len(result.items) == 1
    assert result.items[0].id == 1


async def test_list_products_filter_by_category() -> None:
    products = [
        make_product(product_id=1, category="REFRIGERATOR"),
        make_product(product_id=2, category="TV"),
        make_product(product_id=3, category="REFRIGERATOR"),
    ]
    service = _make_service(products)

    result = await service.list_products(ProductListParams(category="REFRIGERATOR"))

    assert len(result.items) == 2
    assert all(p.category == "REFRIGERATOR" for p in result.items)


async def test_list_products_filter_by_grade() -> None:
    products = [
        make_product(product_id=1, condition_grade=ConditionGrade.A),
        make_product(product_id=2, condition_grade=ConditionGrade.B),
        make_product(product_id=3, condition_grade=ConditionGrade.C),
    ]
    service = _make_service(products)

    result = await service.list_products(ProductListParams(grade=ConditionGrade.B))

    assert len(result.items) == 1
    assert result.items[0].id == 2


async def test_list_products_filter_min_price() -> None:
    products = [
        make_product(product_id=1, price=100_000),
        make_product(product_id=2, price=300_000),
        make_product(product_id=3, price=500_000),
    ]
    service = _make_service(products)

    result = await service.list_products(ProductListParams(min_price=300_000))

    ids = {p.id for p in result.items}
    assert ids == {2, 3}


async def test_list_products_filter_max_price() -> None:
    products = [
        make_product(product_id=1, price=100_000),
        make_product(product_id=2, price=300_000),
        make_product(product_id=3, price=500_000),
    ]
    service = _make_service(products)

    result = await service.list_products(ProductListParams(max_price=300_000))

    ids = {p.id for p in result.items}
    assert ids == {1, 2}


async def test_list_products_filter_warranty_only() -> None:
    products = [
        make_product(product_id=1, warranty_works=True),
        make_product(product_id=2, warranty_works=False),
        make_product(product_id=3, warranty_works=True),
    ]
    service = _make_service(products)

    result = await service.list_products(ProductListParams(warranty=True))

    assert len(result.items) == 2
    assert all(p.warranty_works for p in result.items)


async def test_list_products_search_matches_title() -> None:
    products = [
        make_product(product_id=1, title="LG 세탁기 드럼"),
        make_product(product_id=2, title="삼성 냉장고"),
        make_product(product_id=3, title="LG 에어컨"),
    ]
    service = _make_service(products)

    result = await service.list_products(ProductListParams(q="LG"))

    ids = {p.id for p in result.items}
    assert ids == {1, 3}


async def test_list_products_search_matches_brand() -> None:
    products = [
        make_product(product_id=1, brand="LG전자", title="세탁기"),
        make_product(product_id=2, brand="삼성전자", title="냉장고"),
    ]
    service = _make_service(products)

    result = await service.list_products(ProductListParams(q="삼성"))

    assert len(result.items) == 1
    assert result.items[0].id == 2


async def test_list_products_sort_price_asc() -> None:
    products = [
        make_product(product_id=1, price=500_000),
        make_product(product_id=2, price=100_000),
        make_product(product_id=3, price=300_000),
    ]
    service = _make_service(products)

    result = await service.list_products(ProductListParams(sort=ProductSort.PRICE_ASC))

    prices = [p.price for p in result.items]
    assert prices == sorted(prices)


async def test_list_products_sort_price_desc() -> None:
    products = [
        make_product(product_id=1, price=500_000),
        make_product(product_id=2, price=100_000),
        make_product(product_id=3, price=300_000),
    ]
    service = _make_service(products)

    result = await service.list_products(ProductListParams(sort=ProductSort.PRICE_DESC))

    prices = [p.price for p in result.items]
    assert prices == sorted(prices, reverse=True)


async def test_list_products_pagination_meta() -> None:
    """total=7, size=3 → total_pages=3, 마지막 페이지 2건."""
    products = [
        make_product(product_id=i) for i in range(1, 8)  # 7개
    ]
    service = _make_service(products)

    result = await service.list_products(ProductListParams(page=1, size=3))

    assert result.meta.total == 7
    assert result.meta.total_pages == 3
    assert len(result.items) == 3

    last_page = await service.list_products(ProductListParams(page=3, size=3))
    assert len(last_page.items) == 1


async def test_list_products_thumbnail_from_first_image() -> None:
    img1 = make_image(image_id=1, url="https://cdn.example.com/front.jpg", sort_order=0)
    img2 = make_image(image_id=2, url="https://cdn.example.com/side.jpg", sort_order=1)
    product = make_product(product_id=1, images=[img1, img2])
    service = _make_service([product])

    result = await service.list_products(ProductListParams())

    assert result.items[0].thumbnail_url == "https://cdn.example.com/front.jpg"


async def test_list_products_thumbnail_null_when_no_images() -> None:
    product = make_product(product_id=1, images=[])
    service = _make_service([product])

    result = await service.list_products(ProductListParams())

    assert result.items[0].thumbnail_url is None


async def test_list_products_discount_pct_computed() -> None:
    """price=300_000, original_price=500_000 → discount_pct=40."""
    product = make_product(product_id=1, price=300_000, original_price=500_000)
    service = _make_service([product])

    result = await service.list_products(ProductListParams())

    assert result.items[0].discount_pct == 40


async def test_list_products_discount_pct_null_without_original_price() -> None:
    product = make_product(product_id=1, original_price=None)
    service = _make_service([product])

    result = await service.list_products(ProductListParams())

    assert result.items[0].discount_pct is None


# ── get_product ───────────────────────────────────────────────


async def test_get_product_returns_detail() -> None:
    img = make_image(image_id=1, url="https://cdn.example.com/front.jpg", label="정면")
    product = make_product(product_id=42, title="LG 냉장고", images=[img])
    service = _make_service([product])

    detail = await service.get_product(42)

    assert detail.id == 42
    assert detail.title == "LG 냉장고"
    assert detail.description == "상세 설명"
    assert len(detail.images) == 1
    assert detail.images[0].url == "https://cdn.example.com/front.jpg"
    assert detail.images[0].label == "정면"
    assert detail.thumbnail_url == "https://cdn.example.com/front.jpg"


async def test_get_product_raises_not_found() -> None:
    service = _make_service([])

    with pytest.raises(ProductNotFound):
        await service.get_product(999)


# ── get_featured ─────────────────────────────────────────────


async def test_get_featured_returns_latest_active() -> None:
    """ACTIVE 최신 4건 — INACTIVE 제외, id 내림차순(최신 프록시)."""
    products = [
        make_product(product_id=i, status=ProductStatus.ACTIVE) for i in range(1, 7)
    ] + [make_product(product_id=10, status=ProductStatus.INACTIVE)]
    service = _make_service(products)

    featured = await service.get_featured(limit=4)

    assert len(featured) == 4
    ids = [p.id for p in featured]
    assert ids == sorted(ids, reverse=True)  # 최신순
    assert all(p.id != 10 for p in featured)  # INACTIVE 제외


# ── get_categories ────────────────────────────────────────────


async def test_get_categories_sorted_by_sort_order() -> None:
    categories = [
        make_category(category_id="KITCHEN", sort_order=5),
        make_category(category_id="REFRIGERATOR", sort_order=1),
        make_category(category_id="TV", sort_order=3),
    ]
    service = _make_service([], categories=categories)

    result = await service.get_categories()

    orders = [c.sort_order for c in result]
    assert orders == sorted(orders)


async def test_get_categories_all_have_required_fields() -> None:
    categories = [
        make_category(category_id="REFRIGERATOR", title="냉장고", icon="fridge", sort_order=1),
        make_category(category_id="TV", title="TV", icon="tv", sort_order=3),
    ]
    service = _make_service([], categories=categories)

    for cat in await service.get_categories():
        assert cat.id
        assert cat.label
        assert cat.icon
        assert cat.sort_order > 0


# ── get_products_by_ids ───────────────────────────────────────


async def test_get_products_by_ids_returns_matching() -> None:
    """요청한 ID 의 상품만 반환."""
    products = [make_product(product_id=i) for i in range(1, 6)]
    service = _make_service(products)

    result = await service.get_products_by_ids([1, 3, 5])

    ids = {p.id for p in result}
    assert ids == {1, 3, 5}


async def test_get_products_by_ids_ignores_missing_ids() -> None:
    """일부 ID 가 없어도 존재하는 상품만 반환 — 에러 없음."""
    products = [make_product(product_id=1), make_product(product_id=2)]
    service = _make_service(products)

    result = await service.get_products_by_ids([1, 2, 999])

    ids = {p.id for p in result}
    assert ids == {1, 2}
