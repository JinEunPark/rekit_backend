"""모든 도메인 모델을 한 자리에 import 해서 SQLAlchemy 메타데이터에 등록한다.

Alembic autogenerate 와 앱 부팅 양쪽에서 이 모듈만 import 하면
모듈 간 import 순서 걱정 없이 모든 테이블이 잡힌다.

새 도메인 모듈을 추가하면 여기에 import 한 줄을 더해야 한다.
"""

from app.address.models import Address  # noqa: F401
from app.auth.models import IdentityVerification  # noqa: F401
from app.cart.models import CartItem  # noqa: F401
from app.catalog.models import Product, ProductImage  # noqa: F401
from app.db.base import Base
from app.order.models import Order, OrderItem  # noqa: F401
from app.order.shipment import Shipment  # noqa: F401
from app.payment.models import Payment  # noqa: F401
from app.user.models import User  # noqa: F401

__all__ = ["Base"]
