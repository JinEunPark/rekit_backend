"""API v1 묶음 라우터.

도메인별 APIRouter 들을 하나의 v1 묶음에 합친 뒤, main.py 가 이 묶음만 등록한다.

이유:
- main.py 가 도메인 추가마다 `include_router(..., prefix=settings.api_v1_prefix)`
  를 반복하지 않아도 됨 (DRY).
- v1 → v2 마이그레이션 시 이 파일 하나만 분기 (또는 v2.py 추가) — 영향 면적 최소화.
- API 스펙 전체 모양을 한 곳에서 조망 가능.

새 도메인 추가 절차:
1. app/<domain>/<domain>_router.py 에서 router 정의 (prefix 는 도메인만, 예: '/users')
2. 여기에 import + api_v1.include_router(<domain>_router) 한 줄 추가
3. 끝. main.py 는 안 건드림.

주의: api_v1 자체에 prefix 가 붙으므로, 각 도메인 라우터의 prefix 는 도메인만 적는다.
예) auth_router = APIRouter(prefix='/auth') → 최종 경로 /api/v1/auth/...
"""

from fastapi import APIRouter

from app.address.address_router import router as address_router
from app.admin.dashboard_router import router as admin_dashboard_router
from app.admin.sales_router import router as admin_sales_router
from app.auth.auth_router import router as auth_router
from app.cart.cart_router import router as cart_router
from app.catalog.admin_catalog_router import router as admin_catalog_router
from app.catalog.admin_category_router import router as admin_category_router
from app.catalog.catalog_router import router as catalog_router
from app.common.uploads import router as uploads_router
from app.help.router import router as help_router
from app.help.admin_router import router as admin_help_router
from app.core.config import settings
from app.favorites.favorites_router import router as favorites_router
from app.order.admin_order_router import router as admin_order_router
from app.order.order_router import router as order_router
from app.payment.payment_router import router as payment_router
from app.user.admin_members_router import router as admin_members_router
from app.user.user_router import router as user_router

api_v1 = APIRouter(prefix=settings.api_v1_prefix)

api_v1.include_router(uploads_router)
api_v1.include_router(auth_router)
api_v1.include_router(user_router)
api_v1.include_router(address_router)
api_v1.include_router(catalog_router)
api_v1.include_router(admin_catalog_router)
api_v1.include_router(admin_category_router)
api_v1.include_router(admin_members_router)
api_v1.include_router(admin_order_router)
api_v1.include_router(admin_dashboard_router)
api_v1.include_router(admin_sales_router)
api_v1.include_router(cart_router)
api_v1.include_router(favorites_router)
api_v1.include_router(order_router)
api_v1.include_router(payment_router)
api_v1.include_router(help_router)
api_v1.include_router(admin_help_router)
