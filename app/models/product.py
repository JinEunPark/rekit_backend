import enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Identity, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.cart import CartItem


class ProductCategory(str, enum.Enum):
    REFRIGERATOR = "REFRIGERATOR"  # 냉장고
    WASHING_MACHINE = "WASHING_MACHINE"  # 세탁기
    TV = "TV"
    AIR_CONDITIONER = "AIR_CONDITIONER"  # 에어컨
    KITCHEN = "KITCHEN"  # 주방가전
    ETC = "ETC"  # 기타


class ConditionGrade(str, enum.Enum):
    A = "A"  # 거의 새 것
    B = "B"  # 사용감 있음
    C = "C"  # 흠집 많음, 동작 OK


class ProductStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SOLD_OUT = "SOLD_OUT"


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Identity(always=False), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[ProductCategory] = mapped_column(
        Enum(ProductCategory, native_enum=False, length=30), index=True, nullable=False
    )
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    year_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)

    condition_grade: Mapped[ConditionGrade] = mapped_column(
        Enum(ConditionGrade, native_enum=False, length=5), nullable=False
    )
    warranty_works: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    price: Mapped[int] = mapped_column(Integer, nullable=False)
    original_price: Mapped[int | None] = mapped_column(Integer, nullable=True)

    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    width_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    depth_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)

    stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[ProductStatus] = mapped_column(
        Enum(ProductStatus, native_enum=False, length=20),
        default=ProductStatus.ACTIVE,
        index=True,
        nullable=False,
    )

    images: Mapped[list["ProductImage"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.sort_order",
    )
    cart_items: Mapped[list["CartItem"]] = relationship(back_populates="product")


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(Identity(always=False), primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False
    )
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    label: Mapped[str | None] = mapped_column(String(20), nullable=True)

    product: Mapped[Product] = relationship(back_populates="images")
