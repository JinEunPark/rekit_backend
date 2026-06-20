from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.catalog.models import Product


class Favorite(Base, TimestampMixin):
    """관심상품. (user_id, product_id) composite PK — 멱등 INSERT 보장.

    back_populates 없는 단방향 relationship — User/Product 모델 수정 없이 독립 모듈 유지.
    """

    __tablename__ = "favorites"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        comment="소유 사용자 FK. 탈퇴 시 cascade 삭제",
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        primary_key=True,
        comment="관심 상품 FK. 상품 삭제 시 cascade 삭제",
    )

    product: Mapped["Product"] = relationship()
