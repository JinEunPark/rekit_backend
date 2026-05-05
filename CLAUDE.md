# Rekle Backend — Claude Code 가이드

> 이 파일은 Claude Code 가 자동으로 읽어 컨텍스트로 사용한다.
> 사람도 읽기 쉽게 작성한다 (= README 의 개발 규약 섹션).

## 프로젝트 개요

- **무엇**: 한국 중고/철거 가전 직거래 플랫폼 MVP 백엔드
- **스택**: FastAPI + SQLAlchemy 2.0 (async) + Alembic + PostgreSQL + Redis + S3 호환 스토리지
- **아키텍처**: Modular Monolith + Layered (기본) + Ports & Adapters (외부 통합 모듈만)
- **상세**: `docs/api.md` (API 스펙), `docs/todo.md` (구현 순서), `docs/요구사항정의서.md` (도메인 요구사항)

## 모듈 구조

```
app/
├── core/        # config, deps, security, exceptions, pagination — 공용 인프라
├── db/          # base (DeclarativeBase), registry (모든 모델 등록 — Alembic용)
├── auth/        # 인증 (JWT, OTP, 본인인증) — adapters/ 에 OTP·OAuth port
├── user/        # 사용자 프로필
├── catalog/     # 상품, 카테고리, 검색
├── cart/        # 장바구니
├── address/     # 배송지
├── order/       # 주문 + 배송(shipment.py) — 같은 aggregate
├── payment/     # 결제 — ports.py 에 PaymentGateway, adapters/ 에 PG 구현
├── common/      # storage(port + S3 adapter), uploads(router)
└── main.py
```

**모듈 의존성 규칙**:
- `router → service → repository → models` 일방향
- `router` 가 `repository` 직접 호출 금지
- `service` 는 외부 시스템에 **port (Protocol) 로만** 접근. SDK 직접 import 금지
- 모듈 간 cross-import: FK/relationship 은 string ref 로 OK. `models.py` 가 다른 모듈 model 을 직접 import 금지 (`TYPE_CHECKING` 만 허용)
- 새 도메인 추가 시 `app/db/registry.py` 에 모델 import 한 줄 추가 필수

## TDD 기반 개발 플로우

이 프로젝트는 **Red → Green → Refactor** 의 TDD 사이클을 기본으로 한다.
"테스트가 먼저, 구현은 그 다음" — 모든 새 기능과 버그 수정은 이 흐름을 따른다.

### 1. Red — 실패하는 테스트부터 작성

새 기능을 구현하기 전에 **무엇이 동작해야 하는지 테스트로 먼저 정의**한다.

- 테스트 파일: `tests/test_<module>_<feature>.py`
- 테스트 함수명: `test_<대상>_<상황>_<기대동작>` 형식 (예: `test_page_params_rejects_zero_page`)
- 한 테스트 = 한 가지 동작만 검증
- 경계값 (boundary) 과 실패 케이스 (negative path) 를 정상 케이스 (happy path) 보다 먼저 적는다

```bash
.venv/bin/pytest tests/test_xxx.py -v       # 실패 확인 (Red)
```

### 2. Green — 테스트가 통과하는 최소 구현

- 가장 단순하게 통과시키는 코드만 작성. 미리 일반화 (premature abstraction) 금지
- 다른 테스트가 깨지지 않는지 확인

```bash
.venv/bin/pytest -v                          # 전체 회귀 (Green)
```

### 3. Refactor — 통과 상태 유지하며 개선

- 중복 제거, 명명 개선, 작은 함수로 추출
- 이 단계에서 **새 행동을 추가하지 않는다** (그건 다음 Red 사이클의 일)
- 매 변경 후 `pytest` 재실행

### 4. 단위 vs 통합 테스트 — 어느 걸 먼저?

| 종류 | 위치 | 언제 |
|---|---|---|
| **단위** | `tests/test_<module>.py` | Pydantic 검증, 순수 함수, 도메인 로직 (DB·Redis 불필요) |
| **통합** | `tests/integration/test_<module>_<route>.py` | 라우터 ↔ DB ↔ 외부 어댑터 결합 검증 |

**원칙**: 단위 테스트로 막을 수 있는 건 단위 테스트로 막는다. 라우터 통합 테스트는 단위로 못 잡는 결합(쿼리 정확성·트랜잭션 경계·인증 가드) 만 검증.

### 5. 테스트 작성 규칙

- **이름은 한국어 OK** — docstring 으로 의도를 명확히. 함수명은 영문 snake_case
- **AAA 패턴** — Arrange (준비) / Act (실행) / Assert (검증) 순서로 분리
- **Pydantic 검증** — `pytest.raises(ValidationError)` 로 검증 (= JPA 의 `assertThrows(ConstraintViolationException, ...)`)
- **DB 통합 테스트** — `pytest-asyncio` + `AsyncSession` fixture, 매 테스트마다 트랜잭션 rollback
- **외부 어댑터** — Protocol 기반이라 fake 구현체로 교체 (`app.dependency_overrides[get_payment_gateway] = lambda: FakeGateway()`)

### 6. 커버리지

- 새 PR 머지 전에 **변경된 파일의 라인 커버리지 ≥ 80%** 권장
- 커버리지 확인:
  ```bash
  .venv/bin/pytest --cov=app --cov-report=term-missing
  ```

### 7. 사이클 예시 — `PageParams` 추가 흐름

1. **Red**: `tests/test_pagination.py` 에 `test_page_params_rejects_zero_page` 작성 → 실행 → ImportError 또는 AssertionError 로 실패
2. **Green**: `app/core/pagination.py` 에 `PageParams(BaseModel)` 작성 (`page: int = Field(1, ge=1)`) → 통과
3. **Refactor**: 다른 페이지네이션 헬퍼 (`page_meta`) 도 같은 파일에 정리, 이름 일관화
4. 다음 Red 사이클: `test_cursor_params_rejects_limit_over_max` ...

## 자주 쓰는 명령

| 작업 | 명령 |
|---|---|
| dev 의존성 설치 | `.venv/bin/pip install -e ".[dev]"` |
| 인프라 컨테이너 | `docker compose up -d postgres redis seaweedfs` |
| 마이그레이션 적용 | `.venv/bin/alembic upgrade head` |
| 마이그레이션 생성 | `.venv/bin/alembic revision --autogenerate -m "msg"` |
| 서버 실행 | `.venv/bin/uvicorn app.main:app --reload` |
| 전체 테스트 | `.venv/bin/pytest -v` |
| 단일 파일 | `.venv/bin/pytest tests/test_pagination.py -v` |
| 커버리지 | `.venv/bin/pytest --cov=app --cov-report=term-missing` |
| Lint | `.venv/bin/ruff check app` |
| Type check | `.venv/bin/mypy app` |

## 코드 스타일

- **Ruff** — `pyproject.toml` 의 룰셋 따름 (E, F, I, N, UP, B, SIM, RUF)
- **Type hints** — 모든 함수 시그니처에 명시. `mypy --strict` 통과 목표
- **Docstring** — 클래스 / 모듈 / 비자명한 함수에. 한국어 OK
- **Comment** — WHY 만 작성. WHAT 은 코드와 이름이 말하게 함
- **Import 순서** — stdlib → 외부 라이브러리 → 로컬 (`from app...`). Ruff 가 자동 정렬
- **DateTime / 타임존** — **모든 시간은 UTC**
  - Python: `datetime.now(timezone.utc)` 만 사용. `datetime.utcnow()` / `datetime.now()` (naive) 금지
  - SQLAlchemy 컬럼: 항상 `DateTime(timezone=True)` (Postgres `timestamptz`)
  - JWT `iat`/`exp`: UTC Unix timestamp (라이브러리가 자동 처리하지만 datetime 입력은 UTC-aware 여야 함)
  - API 응답: ISO-8601 + Z suffix (`2026-05-03T09:00:00Z`)
  - **서버 TZ 가 무엇이든 코드는 UTC 로 통일**. 표시(KST 변환)는 클라이언트 책임

## 환경변수

- `app/core/config.py` 에 `Settings` 로 정의 → 코드는 `from app.core.config import settings` 로 접근
- 새 변수 추가 시 **3곳 동시 수정**: `config.py`, `.env.example`, 본인 `.env`
- 민감/환경별 다른 값(시크릿·URL·키)은 default 두지 말 것 (production 누락 silent 방지)
- 동작 튜닝값(pool size, region) 은 default OK
