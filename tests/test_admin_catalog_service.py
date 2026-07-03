"""관리자 상품 CRUD 서비스 단위 테스트.

DB 없이 fake repo + in-memory Product 객체로 도메인 로직 검증.
- 전체 상태 조회 (ACTIVE + INACTIVE + SOLD_OUT)
- 상태 필터 조회
- 키워드 검색
- 상품 생성 (이미지 포함, sort_order 순서)
- 상품 단건 조회 (성공 / NotFound)
- 부분 업데이트 (변경 필드만)
- 소프트 삭제 (status → INACTIVE)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.catalog.admin_catalog_schemas import (
    AdminImageItem,
    AdminProductCreate,
    AdminProductImagesReplace,
    AdminProductImageUpdate,
    AdminProductListParams,
    AdminProductUpdate,
)
from app.catalog.admin_catalog_service import AdminCatalogService
from app.catalog.models import (
    ConditionGrade,
    Product,
    ProductImage,
    ProductStatus,
)
from app.core.exceptions import ProductImageNotFoundError, ProductNotFoundError

# ── 팩토리 ──────────────────────────────────────────────────


def make_product(
    *,
    product_id: int = 1,
    title: str = "테스트 냉장고",
    status: ProductStatus = ProductStatus.ACTIVE,
    brand: str | None = None,
    model_name: str | None = None,
    images: list[ProductImage] | None = None,
) -> Product:
    p = Product(
        title=title,
        description="",
        category="REFRIGERATOR",
        condition_grade=ConditionGrade.A,
        warranty_works=True,
        price=300_000,
        stock=1,
        status=status,
        brand=brand,
        model_name=model_name,
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
    label: str | None = None,
) -> ProductImage:
    img = ProductImage(url=url, sort_order=sort_order, label=label)
    img.id = image_id
    return img


# ── Fake repo ────────────────────────────────────────────────


class _FakeAdminCatalogRepo:
    """Python 리스트 기반 — SQL 없이 관리자 필터·페이지네이션 재현.

    get_by_id / admin_get_list / save / delete 를 구현한다.
    """

    def __init__(self, products: list[Product] | None = None) -> None:
        self._products: list[Product] = list(products or [])
        self._next_id = max((p.id for p in self._products), default=0) + 1  # type: ignore[arg-type]
        self._next_image_id = 10

    async def get_by_id(self, product_id: int) -> Product | None:
        return next((p for p in self._products if p.id == product_id), None)

    async def admin_get_list(
        self,
        params: AdminProductListParams,
    ) -> tuple[list[Product], int]:
        items = list(self._products)

        # status 필터 — None 이면 전체
        if params.status is not None:
            items = [p for p in items if p.status == params.status]

        # 키워드 검색 (제목/브랜드/모델명)
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

        # 최신순 (created_at 내림차순, id 내림차순 fallback)
        items = sorted(items, key=lambda p: p.id, reverse=True)  # type: ignore[arg-type]

        start = (params.page - 1) * params.size
        return items[start : start + params.size], total

    async def replace_images(
        self, product: Product, images: list[ProductImage]
    ) -> Product:
        product.images.clear()
        for img in images:
            img.id = self._next_image_id
            self._next_image_id += 1
            product.images.append(img)
        return product

    async def save(self, product: Product) -> Product:
        """신규 저장 또는 이미 등록된 상품 갱신."""
        existing = next(
            (p for p in self._products if p.id == product.id), None
        )
        if existing is None:
            product.id = self._next_id  # type: ignore[assignment]
            self._next_id += 1
            # server_default 시뮬레이션
            if product.created_at is None:
                product.created_at = datetime.now(UTC)
            # 이미지 ID 채번
            for img in product.images:
                if img.id is None:
                    img.id = self._next_image_id  # type: ignore[assignment]
                    self._next_image_id += 1
            self._products.append(product)
        return product


def _make_service(
    products: list[Product] | None = None,
) -> tuple[AdminCatalogService, _FakeAdminCatalogRepo]:
    repo = _FakeAdminCatalogRepo(products)
    service = AdminCatalogService(repo)  # type: ignore[arg-type]
    return service, repo


# ── list_products ────────────────────────────────────────────


async def test_list_products_all_statuses() -> None:
    """status 필터 없으면 ACTIVE·INACTIVE·SOLD_OUT 모두 반환."""
    products = [
        make_product(product_id=1, status=ProductStatus.ACTIVE),
        make_product(product_id=2, status=ProductStatus.INACTIVE),
        make_product(product_id=3, status=ProductStatus.SOLD_OUT),
    ]
    service, _ = _make_service(products)

    result = await service.list_products(AdminProductListParams())

    assert result.meta.total == 3
    ids = {item.id for item in result.items}
    assert ids == {1, 2, 3}


async def test_list_products_filter_by_status() -> None:
    """status=INACTIVE → INACTIVE 상품만 반환."""
    products = [
        make_product(product_id=1, status=ProductStatus.ACTIVE),
        make_product(product_id=2, status=ProductStatus.INACTIVE),
        make_product(product_id=3, status=ProductStatus.INACTIVE),
    ]
    service, _ = _make_service(products)

    result = await service.list_products(
        AdminProductListParams(status=ProductStatus.INACTIVE)
    )

    assert result.meta.total == 2
    assert all(item.status == ProductStatus.INACTIVE for item in result.items)


async def test_list_products_search_keyword() -> None:
    """q='삼성' → 제목·브랜드·모델명 중 하나라도 매칭되는 상품만 반환."""
    products = [
        make_product(product_id=1, title="삼성 냉장고", brand="삼성전자"),
        make_product(product_id=2, title="LG 세탁기", brand="LG전자"),
        make_product(product_id=3, title="드럼 세탁기", brand=None, model_name="삼성WF70"),
    ]
    service, _ = _make_service(products)

    result = await service.list_products(AdminProductListParams(q="삼성"))

    ids = {item.id for item in result.items}
    assert ids == {1, 3}


# ── create_product ────────────────────────────────────────────


async def test_create_product_success() -> None:
    """신규 상품 생성 — 필드값 + 이미지 2개 포함."""
    service, _ = _make_service()

    data = AdminProductCreate(
        title="LG 냉장고 462L",
        description="깨끗한 상품",
        category="REFRIGERATOR",
        condition_grade=ConditionGrade.B,
        warranty_works=True,
        price=250_000,
        stock=1,
        image_urls=[
            "https://cdn.example.com/a.jpg",
            "https://cdn.example.com/b.jpg",
        ],
    )

    result = await service.create_product(data)

    assert result.title == "LG 냉장고 462L"
    assert result.price == 250_000
    assert result.condition_grade == ConditionGrade.B
    assert len(result.images) == 2
    assert result.images[0].url == "https://cdn.example.com/a.jpg"
    assert result.images[1].url == "https://cdn.example.com/b.jpg"


async def test_create_product_images_sort_order() -> None:
    """image_urls 의 리스트 순서대로 sort_order 0, 1, 2 ... 로 할당."""
    service, _ = _make_service()

    urls = [
        "https://cdn.example.com/front.jpg",
        "https://cdn.example.com/side.jpg",
        "https://cdn.example.com/back.jpg",
    ]
    data = AdminProductCreate(
        title="테스트 TV",
        category="TV",
        condition_grade=ConditionGrade.A,
        warranty_works=False,
        price=100_000,
        stock=2,
        image_urls=urls,
    )

    result = await service.create_product(data)

    for i, img in enumerate(result.images):
        assert img.sort_order == i
        assert img.url == urls[i]


# ── get_product ───────────────────────────────────────────────


async def test_get_product_success() -> None:
    """존재하는 상품 ID 조회 → 상세 정보 반환."""
    img = make_image(image_id=1, url="https://cdn.example.com/front.jpg")
    product = make_product(product_id=42, title="LG 냉장고", images=[img])
    service, _ = _make_service([product])

    result = await service.get_product(42)

    assert result.id == 42
    assert result.title == "LG 냉장고"
    assert len(result.images) == 1
    assert result.images[0].url == "https://cdn.example.com/front.jpg"


async def test_get_product_not_found() -> None:
    """존재하지 않는 ID → ProductNotFoundError 예외."""
    service, _ = _make_service([])

    with pytest.raises(ProductNotFoundError):
        await service.get_product(999)


# ── update_product ────────────────────────────────────────────


async def test_update_product_partial() -> None:
    """title 만 변경 → 나머지 필드는 원래 값 유지."""
    product = make_product(product_id=1, title="구 제목", status=ProductStatus.ACTIVE)
    service, _ = _make_service([product])

    result = await service.update_product(1, AdminProductUpdate(title="새 제목"))

    assert result.title == "새 제목"
    assert result.price == 300_000  # 원래 값 유지
    assert result.status == ProductStatus.ACTIVE  # 원래 값 유지


async def test_update_product_not_found() -> None:
    """존재하지 않는 ID 업데이트 → ProductNotFoundError 예외."""
    service, _ = _make_service([])

    with pytest.raises(ProductNotFoundError):
        await service.update_product(999, AdminProductUpdate(title="제목"))


# ── delete_product ────────────────────────────────────────────


async def test_delete_product_soft_delete() -> None:
    """소프트 삭제 — status 가 INACTIVE 로 변경되고, DB에서 지워지지 않는다."""
    product = make_product(product_id=1, status=ProductStatus.ACTIVE)
    service, repo = _make_service([product])

    await service.delete_product(1)

    # repo 에 여전히 남아 있어야 함 (소프트 삭제)
    remaining = await repo.get_by_id(1)
    assert remaining is not None
    assert remaining.status == ProductStatus.INACTIVE


async def test_delete_product_not_found() -> None:
    """존재하지 않는 ID 삭제 → ProductNotFoundError 예외."""
    service, _ = _make_service([])

    with pytest.raises(ProductNotFoundError):
        await service.delete_product(999)


# ── replace_images ────────────────────────────────────────────


async def test_replace_images_adds_new_images() -> None:
    """이미지가 없는 상품에 2개 추가 → 응답에 2개 이미지 포함."""
    product = make_product(product_id=1)
    service, _ = _make_service([product])

    data = AdminProductImagesReplace(
        images=[
            AdminImageItem(url="https://cdn.example.com/front.jpg", label="FRONT"),
            AdminImageItem(url="https://cdn.example.com/side.jpg", label="SIDE"),
        ]
    )

    result = await service.replace_images(1, data)

    assert len(result.images) == 2
    assert result.images[0].url == "https://cdn.example.com/front.jpg"
    assert result.images[0].sort_order == 0  # 배열 인덱스에서 자동 부여
    assert result.images[0].label == "FRONT"
    assert result.images[1].url == "https://cdn.example.com/side.jpg"
    assert result.images[1].sort_order == 1


async def test_replace_images_replaces_existing() -> None:
    """기존 이미지 2개 → 새 이미지 1개로 교체 시 기존 이미지 사라짐."""
    product = make_product(
        product_id=1,
        images=[
            make_image(image_id=1, url="https://cdn.example.com/old1.jpg", sort_order=0),
            make_image(image_id=2, url="https://cdn.example.com/old2.jpg", sort_order=1),
        ],
    )
    service, _ = _make_service([product])

    data = AdminProductImagesReplace(
        images=[
            AdminImageItem(url="https://cdn.example.com/new.jpg"),
        ]
    )

    result = await service.replace_images(1, data)

    assert len(result.images) == 1
    assert result.images[0].url == "https://cdn.example.com/new.jpg"


async def test_replace_images_reorders() -> None:
    """sort_order 값 변경으로 순서 재정렬 확인."""
    product = make_product(
        product_id=1,
        images=[
            make_image(image_id=1, url="https://cdn.example.com/a.jpg", sort_order=0),
            make_image(image_id=2, url="https://cdn.example.com/b.jpg", sort_order=1),
        ],
    )
    service, _ = _make_service([product])

    # a↔b 순서 바꾸기 — 배열 순서 = sort_order
    data = AdminProductImagesReplace(
        images=[
            AdminImageItem(url="https://cdn.example.com/b.jpg"),
            AdminImageItem(url="https://cdn.example.com/a.jpg"),
        ]
    )

    result = await service.replace_images(1, data)

    assert result.images[0].url == "https://cdn.example.com/b.jpg"
    assert result.images[0].sort_order == 0
    assert result.images[1].url == "https://cdn.example.com/a.jpg"
    assert result.images[1].sort_order == 1


async def test_replace_images_empty_clears_all() -> None:
    """빈 리스트 전송 → 모든 이미지 삭제."""
    product = make_product(
        product_id=1,
        images=[make_image(image_id=1, url="https://cdn.example.com/img.jpg")],
    )
    service, _ = _make_service([product])

    result = await service.replace_images(1, AdminProductImagesReplace(images=[]))

    assert result.images == []


async def test_replace_images_product_not_found() -> None:
    """존재하지 않는 상품 ID → ProductNotFoundError 예외."""
    service, _ = _make_service([])

    with pytest.raises(ProductNotFoundError):
        await service.replace_images(999, AdminProductImagesReplace(images=[]))


# ── update_image ─────────────────────────────────────────────


async def test_update_image_product_not_found() -> None:
    """존재하지 않는 상품 ID → ProductNotFoundError 예외."""
    service, _ = _make_service([])

    with pytest.raises(ProductNotFoundError):
        await service.update_image(999, 1, AdminProductImageUpdate(url="https://cdn.example.com/new.jpg"))


async def test_update_image_not_found() -> None:
    """상품은 있지만 image_id 가 해당 상품 소유가 아니거나 없음 → ProductImageNotFoundError 예외."""
    product = make_product(product_id=1, images=[make_image(image_id=1)])
    service, _ = _make_service([product])

    with pytest.raises(ProductImageNotFoundError):
        await service.update_image(1, 999, AdminProductImageUpdate(url="https://cdn.example.com/new.jpg"))


async def test_update_image_replaces_url_only() -> None:
    """url 만 전송 → url 만 변경되고 label 은 유지."""
    product = make_product(
        product_id=1,
        images=[make_image(image_id=1, url="https://cdn.example.com/old.jpg", label="FRONT")],
    )
    service, _ = _make_service([product])

    result = await service.update_image(
        1, 1, AdminProductImageUpdate(url="https://cdn.example.com/new.jpg")
    )

    assert result.images[0].url == "https://cdn.example.com/new.jpg"
    assert result.images[0].label == "FRONT"


async def test_update_image_replaces_label_only() -> None:
    """label 만 전송 → label 만 변경되고 url 은 유지."""
    product = make_product(
        product_id=1,
        images=[make_image(image_id=1, url="https://cdn.example.com/front.jpg", label="FRONT")],
    )
    service, _ = _make_service([product])

    result = await service.update_image(1, 1, AdminProductImageUpdate(label="SIDE"))

    assert result.images[0].url == "https://cdn.example.com/front.jpg"
    assert result.images[0].label == "SIDE"


async def test_update_image_does_not_affect_other_images() -> None:
    """대상 이미지만 변경되고 같은 상품의 다른 이미지는 그대로."""
    product = make_product(
        product_id=1,
        images=[
            make_image(image_id=1, url="https://cdn.example.com/a.jpg", sort_order=0),
            make_image(image_id=2, url="https://cdn.example.com/b.jpg", sort_order=1),
        ],
    )
    service, _ = _make_service([product])

    result = await service.update_image(
        1, 2, AdminProductImageUpdate(url="https://cdn.example.com/b-new.jpg")
    )

    assert result.images[0].url == "https://cdn.example.com/a.jpg"
    assert result.images[1].url == "https://cdn.example.com/b-new.jpg"
