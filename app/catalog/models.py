import enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Identity, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.cart.models import CartItem


class ConditionGrade(str, enum.Enum):
    """상태 등급 — 사진/안내 카드 색상이 이 값으로 결정된다."""

    A = "A"  # 거의 새 것 (mint)
    B = "B"  # 사용감 있음 (yellow)
    C = "C"  # 흠집 많음, 동작 OK (orange)


class ProductStatus(str, enum.Enum):
    """상품 노출/판매 상태."""

    ACTIVE = "ACTIVE"  # 판매중 — 목록/검색 노출
    INACTIVE = "INACTIVE"  # 비공개 — 운영자가 임시 숨김
    SOLD_OUT = "SOLD_OUT"  # 품절 — 재고 0 시 자동 전환


class Product(Base, TimestampMixin):
    """상품 마스터. 단일 판매자(MVP) 가정 — Phase 3 에서 seller_id 추가 예정.

    가격은 `price` (판매가) / `original_price` (정가) 2개. 할인율은 `1 - price/original_price`.
    """

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(
        Identity(always=False),
        primary_key=True,
        comment="상품 PK",
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="상품명. 카드/검색 노출용 — 브랜드+모델+용량 포함 권장",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="상세 설명 (플레인 텍스트). 마크다운/HTML 은 서비스 레이어에서 sanitize",
    )
    category: Mapped[str] = mapped_column(
        String(30),
        index=True,
        nullable=False,
        comment="대분류 ID. product_categories.id 를 FK 없이 참조 (유연성 우선)",
    )
    brand: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="브랜드명 (삼성/LG 등). 카드의 메타라인에 노출",
    )
    model_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="모델명 (RT38K5982SL 등). 검색/AS 식별용",
    )
    year_estimate: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="추정 연식 (yyyy). 철거 가전 특성상 정확한 제조연도가 없어 추정값",
    )

    condition_grade: Mapped[ConditionGrade] = mapped_column(
        Enum(ConditionGrade, native_enum=False, length=5),
        nullable=False,
        comment="상태 등급 A/B/C. 등급별 컬러 뱃지로 시각화",
    )
    warranty_works: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="동작 보증 여부. true 면 카드/상세에 '동작보증' 뱃지 노출",
    )

    price: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="판매가 (원). 통화는 KRW 고정",
    )
    original_price: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="원가/정가 (원). 할인율 계산 기준 — NULL 이면 할인 표기 생략",
    )

    weight_kg: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="제품 무게(kg). 누적 절약 무게 집계와 배송비 산정에 사용",
    )
    width_cm: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="가로 (cm)",
    )
    depth_cm: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="깊이 (cm)",
    )
    height_cm: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="높이 (cm)",
    )

    stock: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="재고 수량. 보통 1개씩이지만 동일 모델 다수 입고 가능",
    )
    status: Mapped[ProductStatus] = mapped_column(
        Enum(ProductStatus, native_enum=False, length=20),
        default=ProductStatus.ACTIVE,
        index=True,
        nullable=False,
        comment="노출 상태. 목록 API 는 ACTIVE 만 조회",
    )

    images: Mapped[list["ProductImage"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.sort_order",
    )
    cart_items: Mapped[list["CartItem"]] = relationship(back_populates="product")


class ProductImage(Base):
    """상품 이미지. sort_order 0 이 대표(정면) 이미지로 관례화.

    label 은 디자인의 6 라벨(정면/측면/내부/흠집/뒷면/제품번호)과 매핑되며
    todo.md §6.3 에서 ProductImageLabel enum 으로 표준화 예정.
    """

    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(
        Identity(always=False),
        primary_key=True,
        comment="이미지 PK",
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="소유 상품 FK (상품 삭제 시 cascade)",
    )
    url: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="S3 객체 URL (uploads/confirm 통과한 키만 허용)",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="갤러리 정렬 순서 (0 부터 오름차순). 0 번이 카드 썸네일",
    )
    label: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="이미지 라벨 (정면/측면/흠집 등). NULL 허용이지만 등급 B/C 는 흠집 권장",
    )

    product: Mapped[Product] = relationship(back_populates="images")


class ProductCategoryMetaItem(Base, TimestampMixin):
    """상품 카테고리 메타 정보. 정적 데이터로 프론트에 전달."""

    __tablename__ = "product_categories"

    id: Mapped[str] = mapped_column(
        String(30),
        primary_key=True,
        comment="카테고리 식별자 (REFRIGERATOR 등 대문자+언더스코어)",
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[str] = mapped_column(String(50), nullable=False, default="menu")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
