from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Identity, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.catalog.models import Product
    from app.user.models import User


class CartItem(Base, TimestampMixin):
    """장바구니 항목. (user_id, product_id) 유니크 — 같은 상품 재담기 시 quantity 증가.

    비로그인 장바구니는 Redis 세션에 보관하고, 로그인 시 이 테이블로 머지한다.
    """

    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_cart_user_product"),
    )

    id: Mapped[int] = mapped_column(
        Identity(always=False),
        primary_key=True,
        comment="장바구니 항목 PK",
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="소유 사용자 FK. 탈퇴 시 cascade 정리",
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        comment="담긴 상품 FK. 상품 삭제 시 cascade 로 함께 제거",
    )
    quantity: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        comment="수량. 가전은 보통 1 이지만 동일 모델 다수 담기 허용",
    )

    user: Mapped["User"] = relationship(back_populates="cart_items")
    product: Mapped["Product"] = relationship(back_populates="cart_items")
