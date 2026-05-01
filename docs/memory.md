# Rekle Backend 작업 로그

> 철거 가전 직거래 플랫폼 MVP 백엔드 — 현재까지의 셋업 상태 정리.
> 자세한 도메인 요구사항은 [요구사항정의서.md](요구사항정의서.md) 참고.

## 1. 기술 스택 (확정)

| 영역 | 선택 | 비고 |
|---|---|---|
| Backend | FastAPI + Pydantic v2 + SQLAlchemy 2.0 (async) | Python 3.11+ |
| DB | PostgreSQL 15 (asyncpg) | psycopg2 미사용 — alembic도 async 모드 |
| 마이그레이션 | Alembic 1.18 (async env.py) | `[asyncio]` extra로 greenlet 포함 |
| 캐시/큐 | Redis 7 | 세션/캐시 (코드 미연동) |
| 오브젝트 스토리지 | **SeaweedFS** (S3 호환 게이트웨이) | dev: self-hosted, prod: AWS S3 swap 가능 |
| S3 클라이언트 | `aioboto3` 13.x | path-style + SigV4 |
| 컨테이너 | Docker Compose | postgres / redis / seaweedfs / app |
| 의존성 관리 | `pyproject.toml` (PEP 621) | `pip install -e .` |

## 2. 디렉터리 구조

```
rekle_backend/
├── pyproject.toml              의존성 + ruff/pytest 설정
├── .env                        로컬 실행용 (gitignored)
├── .env.example
├── Dockerfile                  python:3.11-slim + gunicorn(uvicorn worker)
├── docker-compose.yml          postgres/redis/seaweedfs/app
├── alembic.ini
├── alembic/
│   ├── env.py                  async 모드 (asyncpg 그대로 사용)
│   ├── script.py.mako
│   └── versions/
│       └── e9bcd41ab78f_init_schema.py
├── infra/seaweedfs/s3_config.json   S3 IAM identity (rekle / anonymous)
├── app/
│   ├── main.py                 FastAPI factory + lifespan(ensure_bucket)
│   ├── core/
│   │   ├── config.py           pydantic-settings (DB/CORS/S3)
│   │   └── database.py         async engine + get_db
│   ├── models/                 도메인 모델 10개 (아래 §3)
│   ├── schemas/upload.py       presign/confirm 요청·응답
│   ├── services/storage.py     SeaweedFS S3 어댑터
│   └── api/v1/uploads.py       presigned URL 발급 + 업로드 검증
└── docs/
    ├── 요구사항정의서.md
    └── memory.md (이 문서)
```

> `app/api/v1/{auth,products,orders,payments,shipments,verifications,admin}` 및 `app/crud/`, `app/schemas/{auth,user,common}.py`, `app/core/{security,dependencies,exceptions}.py`는 의도적으로 제거된 상태. 모델 + 인프라 + 업로드만 우선 셋업하고 비즈니스 로직은 앞으로 단계별로 추가.

## 3. 모델 (10개 — 요구사항 §4와 1:1 매핑)

| 모델 | 핵심 필드 |
|---|---|
| `User` | email, password_hash, role, phone_verified_at, identity_verified_at, ci/di(암호화 예정), birth_date, gender |
| `Address` | user_id, recipient, phone, zipcode, address1/2, is_default |
| `IdentityVerification` | user_id, provider(TOSS/NICE/KCB), result(SUCCESS/FAIL), request_id, verified_at |
| `Product` | category(6종), brand, model_name, year_estimate, **condition_grade(A/B/C)**, warranty_works, price, weight/사이즈, stock, status |
| `ProductImage` | product_id, url, sort_order |
| `CartItem` | user_id, product_id, quantity (UniqueConstraint user+product) |
| `Order` | order_number, total_amount, shipping_fee, status(7단계), 배송지 스냅샷, paid_at |
| `OrderItem` | order_id, product_id, **product_title_snapshot, price_snapshot** (시점 보존) |
| `Payment` | order_id, pg_provider(TOSS/KAKAO/NAVER), pg_tid, method, amount, status |
| `Shipment` | order_id (1:1), method(PARCEL/FREIGHT/DIRECT), carrier, tracking_number, status, last_tracked_at |

- 모든 모델 `Base` + `TimestampMixin`(created_at/updated_at) 상속
- Enum은 전부 `native_enum=False` (PG enum 타입 대신 VARCHAR 저장 — 마이그레이션 부담 감소)
- 메타데이터 일괄 등록은 `app/models/__init__.py`에서 처리 (alembic autogenerate 인식용)

## 4. 환경변수 (.env)

```
APP_ENV=development
DEBUG=true
SECRET_KEY=<openssl rand -hex 32>

DATABASE_URL=postgresql+asyncpg://rekle:rekle@localhost:5432/rekle
CORS_ORIGINS=["http://localhost:5173","http://localhost:3000"]
REDIS_URL=redis://localhost:6379/0

# SeaweedFS (S3 호환)
S3_ENDPOINT_URL=http://localhost:8333
S3_BUCKET=rekle-images
S3_ACCESS_KEY=rekle-dev-access
S3_SECRET_KEY=rekle-dev-secret
S3_PUBLIC_URL_BASE=http://localhost:8333/rekle-images
S3_FORCE_PATH_STYLE=true
```

도커 내부에서는 `app` 서비스 환경변수가 `localhost`를 서비스명(`postgres`, `seaweedfs`)으로 자동 override.

## 5. 인프라 (docker-compose)

| 서비스 | 컨테이너명 | 포트 | 역할 |
|---|---|---|---|
| postgres | rekle-postgres | 5432 | PostgreSQL 15 |
| redis | rekle-redis | 6379 | 캐시/세션 |
| seaweedfs | rekle-seaweedfs | 9333(master) / 8080(volume) / 8888(filer) / **8333(S3)** | 이미지 스토리지 |
| app | rekle-app | 8000 | FastAPI (`alembic upgrade head` → uvicorn) |

SeaweedFS S3는 `infra/seaweedfs/s3_config.json`로 IAM identity 두 개 운영:
- `rekle` (Admin/Read/Write/List/Tagging) — 앱이 사용
- `anonymous` (Read만) — 공개 이미지 GET

## 6. DB / 마이그레이션

- **현재 적용된 리비전**: `e9bcd41ab78f_init_schema` (11개 테이블 + `alembic_version`)
- env.py는 async (`async_engine_from_config` + `connection.run_sync(do_run_migrations)`)
- `sqlalchemy.url`은 ini에 하드코딩하지 않고 `settings.database_url`로 주입

```bash
# 모델 변경 후 새 리비전 생성
.venv/bin/alembic revision --autogenerate -m "add foo column"

# 적용 / 롤백
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1

# 도커 환경
docker compose run --rm app alembic revision --autogenerate -m "msg"
```

## 7. 이미지 업로드 — Presigned URL 패턴

3-step 흐름. 백엔드는 파일 본문을 절대 거치지 않음.

```
[FE]                                    [BE]                       [SeaweedFS]
 |--POST /uploads/presign-------------->|                              |
 |   { content_type: "image/jpeg" }     |--generate_presigned_url----->|
 |<--{ upload_url, key, public_url }----|<-----------------------------|
 |                                                                     |
 |--PUT <upload_url>  (file binary, Content-Type 헤더)---------------->|
 |<--200--------------------------------------------------------------|
 |                                                                     |
 |--POST /uploads/confirm  { key }----->|                              |
 |                                      |--head_object---------------->|
 |                                      |<-----------------------------|
 |<--{ key, public_url, size, ct }-----|  (size 초과 시 자동 delete + 413) |
 |                                                                     |
 |--POST /admin/products  { ..., image_keys: [...] } (← 추후 구현)
```

- 키 포맷: `products/{uuid}.{jpg|png|webp}`
- 허용 Content-Type: `image/jpeg`, `image/png`, `image/webp`
- 최대 크기: 10MB (`s3_max_upload_size`, confirm 단계에서 검증)
- presign 만료: 600초 (`s3_presign_expire_seconds`)
- **TODO**: presign 엔드포인트에 관리자 가드 추가 (auth 복구 후 `Depends(get_current_admin)`)

## 8. main.py 구성

- `lifespan` startup: `storage_service.ensure_bucket()` (SeaweedFS는 버킷 없으면 PUT 실패)
- `lifespan` shutdown: `engine.dispose()`
- CORS: `CORS_ORIGINS` 비어있지 않을 때만 활성화
- Production에서는 `/docs`, `/redoc`, `/openapi.json` 비활성화
- 마운트된 라우터: `/api/v1/uploads/*`, `/health`

## 9. 실행 방법

**전체 도커 실행**
```bash
cp .env.example .env  # 그리고 SECRET_KEY는 openssl rand -hex 32로 교체
docker compose up --build
# Swagger:  http://localhost:8000/docs
```

**로컬 개발 (도커는 인프라만)**
```bash
docker compose up -d postgres redis seaweedfs
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
```

## 10. 다음 단계 (Phase 1 우선순위)

1. **auth 복구** — `core/security.py`(JWT/bcrypt) + `core/dependencies.py`(CurrentUser/CurrentAdmin) + `api/v1/auth.py` (register/login/refresh/me)
2. **SMS 인증** — 회원가입 게이트 (`verifications/sms/*`)
3. **상품 관리** — 관리자 CRUD + 구매자 조회·필터·정렬, presign 엔드포인트에 admin 가드 적용
4. **본인인증 (CI/DI)** — 첫 주문 직전 토스/NICE 연동, **암호화 저장 키 관리 정책 결정 필요** (env vs KMS)
5. **주문 + 토스페이먼츠** — 멱등성 보장한 결제 승인 + 웹훅
6. **관리자 송장 입력** → SHIPPING 자동 전환

## 11. 결정 대기 항목

- CI/DI 암호화 방식 (Fernet env key vs AWS KMS)
- 이미지 리사이징/WebP 변환 위치 (Celery 워커 vs SeaweedFS image filer 옵션)
- Redis 사용처 (배송 추적 캐시 / 비로그인 장바구니 / SMS rate-limit 중 우선)
- 프런트 SEO 대응 (Vue SPA 유지 vs Nuxt 전환)
- 배포 호스팅 (NCP / AWS Lightsail / EC2)
