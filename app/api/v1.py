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

from app.auth.auth_router import router as auth_router
from app.common.uploads import router as uploads_router
from app.core.config import settings

api_v1 = APIRouter(prefix=settings.api_v1_prefix)

api_v1.include_router(uploads_router)
api_v1.include_router(auth_router)
