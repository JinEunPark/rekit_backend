# 결제(Payment) 개발 현황 — 코드 숙지 가이드

> 작성 2026-08-31. Rekle 결제 모듈의 **현재 상태 전부**를 한 문서에.
> 코드 링크는 IDE(VSCode)에서 클릭하면 해당 줄로 이동한다.
> 실제 작업 To-Do 는 [toss_integration.md](toss_integration.md) 를 볼 것 (이 문서는 "이해"용).

Java/Spring 비유: `Service` = `@Service`, `Repository` = Spring Data JPA Repository,
`Protocol` = `interface`, `deps.py` = `@Configuration`(빈 와이어링),
`Depends(...)` = 생성자 주입, `BusinessError` = `@ResponseStatus` 붙은 커스텀 예외.

---

## 0. 30초 요약 — 뭐가 되고 뭐가 안 되나

| 항목 | 상태 |
|---|---|
| 결제 도메인 모델 / 스키마 / 라우터 / 서비스 | ✅ 구현 완료 |
| `init` → `confirm` → `webhook` 플로우 (멱등성, FOR UPDATE 락, 재고 복구) | ✅ 구현 + 테스트 |
| 웹훅 검증 (조회 재확인 방식) | ✅ 2026-08-31 완료 |
| `FakePaymentGateway` 로 로컬 결제 (항상 성공) | ✅ `USE_FAKE_PG=true` |
| `TossPaymentGateway.confirm` / `get_payment` 실제 HTTP 호출 | ✅ 구현됨 (실키로 미검증) |
| **토스 실제 키 / 상점 계약** | ❌ `.env` 비어 있음 |
| **PG 결제 취소·환불 실호출** (`cancel`) | ❌ 미구현 — 주문 취소 시 DB 상태만 바뀜 |
| **프론트엔드 결제 위젯 연동** | ❌ 미연동 — `OrderView.vue` 는 주문 생성 후 바로 완료 페이지로 |
| confirm 실패 사유 저장 / `Idempotency-Key` 헤더 | ❌ Task 5 |
| 가상계좌(계좌이체) 입금대기 흐름 | ❌ 미구현 (`WAITING_FOR_DEPOSIT` 상태 없음) |
| `config.py` 의 `toss_client_key` 필드 | ❌ 없음 (`.env.example` 엔 있음) |
| `docs/api.md` §10 | ⚠️ 옛 설계 기준 — 실제 구현과 불일치 (`/verify`→`/confirm` 등) |

**한 줄 결론**: 백엔드 로직은 거의 다 됐고, 실연동을 막는 건 ①실제 키 ②취소 API ③프론트 위젯.

---

## 1. 전체 결제 플로우

### 1-1. 정상 결제 (해피 패스)

```
[프론트]                        [백엔드]                       [토스]
  │                               │                             │
  │  1. 장바구니 → 주문서          │                             │
  │  POST /orders  ─────────────► create_order()                │
  │                              · 재고 검증 + decrement_stock   │
  │                              · Order(status=PENDING) 생성    │
  │  ◄──────────────────── order_number "RK-2608310001"         │
  │                               │                             │
  │  2. POST /payments/init ────► init_payment()                │
  │     {order_number, method}   · 주문 소유권 + PENDING 확인     │
  │                              · Payment(status=READY) 생성    │
  │  ◄──────────── {payment_id, amount, customer_name}          │
  │                               │                             │
  │  3. 토스 위젯 SDK 로 결제창 ────────────────────────────────► 카드 입력/인증
  │     (clientKey 사용, 서버 안 거침)                            │
  │  ◄───────── successUrl?paymentKey=...&orderId=...&amount=... │
  │                               │                             │
  │  4. POST /payments/confirm ─► confirm_payment()             │
  │     {payment_key, order_id,  · 주문 PENDING + READY Payment  │
  │      amount}                    FOR UPDATE 락으로 조회        │
  │                              · amount == order.total_amount  │
  │                              · gateway.confirm() ──────────► POST /v1/payments/confirm
  │                                                    ◄──────── {status:DONE, card:{...}}
  │                              · Payment→PAID, Order→PAID      │
  │                              · 결제완료 메일 (BackgroundTask) │
  │  ◄──────────── {status:PAID, card_company, card_last4}      │
  │                               │                             │
  │  5. 완료 페이지                 │  (비동기) 웹훅 ◄──────────── PAYMENT_STATUS_CHANGED
  │                               │  handle_webhook()           │
  │                               │  · get_payment() 재조회 → DONE
  │                               │  · 이미 PAID → 멱등 무시      │
```

### 1-2. confirm 은 실패했는데 웹훅이 먼저/대신 도착

`gateway.confirm()` 이 타임아웃(`PaymentGatewayUnknownError`, HTTP 502)나면 프론트에
"결제 확인 중"만 안내하고 주문은 PENDING 유지. 이후 토스 웹훅이 진실을 알려준다:

- 웹훅 `get_payment()` → `DONE` 이면 → `handle_webhook` 이 Payment/Order 를 PAID 로 전환
  (이때 `payment.pg_tid` 가 아직 없으므로 `orderId` fallback 조회 + 카드 메타도 채움)
- `get_payment()` → `ABORTED`/`EXPIRED` 이면 → Payment FAILED + Order 취소 + 재고 복구

### 1-3. 결제 후 취소/환불 (❌ 현재 미완성)

```
사용자: POST /orders/{n}/cancel  ─► order_service.cancel_order()
                                    · _CANCELLABLE_STATUSES 확인
                                    · increment_stock (재고 복구)
                                    · order.status = CANCELLED
                                    ⚠️ 여기서 토스 취소 API 를 안 부른다 → 돈이 안 돌아감
```

토스 쪽에서 관리자가 수동 취소하면 그 웹훅(`get_payment()` → `CANCELED`)으로 우리 DB 는
맞춰지지만, **우리 서비스가 능동적으로 환불을 거는 경로가 없다.** → Task 3·4.

---

## 2. 코드 맵 — 파일별 상세

### 2-1. [app/payment/models.py](../app/payment/models.py) — ORM 모델

| 심볼 | 설명 |
|---|---|
| `PgProvider` (StrEnum) | `TOSS` / `KAKAO` / `NAVER`. MVP 는 `TOSS` 단일. |
| `PaymentMethod` (StrEnum) | `CARD` / `BANK` / `KAKAO_PAY` / `NAVER_PAY` / `TOSS_PAY`. 매출 분석에서 5종 집계. 주문서 화면은 3그룹(카드/계좌이체/간편). |
| `PaymentStatus` (StrEnum) | `READY`→`PAID`→(`CANCELLED`/`PARTIAL_CANCELLED`) / `FAILED`. **웹훅 멱등성의 기준값.** |
| `Payment` (테이블 `payments`) | 결제 트랜잭션 1건. |

`Payment` 주요 컬럼 ([models.py:46](../app/payment/models.py#L46)):

| 컬럼 | 타입 | 의미 |
|---|---|---|
| `id` | Identity PK | |
| `order_id` | FK → `orders.id` (`ondelete=RESTRICT`) | 결제 있는 주문은 삭제 불가. `index=True` |
| `pg_provider` | Enum(20) | `TOSS` |
| `pg_tid` | `String(100)`, **`unique=True`**, nullable | 토스 `paymentKey`. **멱등성 키** — 웹훅 중복 방어용 유니크 제약 |
| `method` | Enum(20) | 결제 수단 |
| `amount` | int | 결제 금액(원). `Order.total_amount` 와 일치해야 |
| `status` | Enum(20), default `READY` | |
| `paid_at` / `cancelled_at` | `timestamptz` nullable | |
| `fail_reason` | `String(500)` nullable | PG 에러 메시지 (사용자 노출 전 정제 필요) |
| `card_company` / `card_last4` / `installment_months` / `approval_number` | | **PCI-DSS 안전 범위 메타데이터만.** 영수증·환불용 |

> **PCI-DSS**: 토스 결제창은 브라우저↔PG 직통이라 카드 PAN 이 우리 서버를 통과하지 않는다
> → SAQ-A 수준만 충족. **절대 저장 금지**: 카드 전체번호, CVC/CVV, 유효기간(단독).
> **저장 OK**: 카드사명, last4, 할부개월, 승인번호, 거래ID.

`relationship`: `Payment.order` ↔ `Order.payments` (string ref, cross-module FK 허용).

### 2-2. [app/payment/payment_schemas.py](../app/payment/payment_schemas.py) — Pydantic DTO

`= JPA 의 Request/Response DTO. Pydantic 이 검증까지 담당(= Bean Validation).`

| 스키마 | 용도 | 필드 |
|---|---|---|
| `PaymentInitRequest` | `POST /payments/init` body | `order_number: str`, `method: PaymentMethod` |
| `PaymentInitResponse` | init 응답 | `payment_id`, `order_number`, `amount`, `customer_name` |
| `PaymentConfirmRequest` | `POST /payments/confirm` body | `payment_key`, `order_id`(=order_number), `amount` |
| `PaymentConfirmResponse` | confirm 응답 (영수증용) | `order_number`, `status`, `paid_at`, `card_company`, `card_last4`, `installment_months` |
| `TossWebhookPayload` | `POST /payments/webhooks/toss` body | `event_type`(alias `eventType`), `data: dict[str, Any]` |
| `PaymentResponse` | 결제 단건 조회 (ORM→변환) | `from_attributes=True` |

> ⚠️ `PaymentInitResponse` 에 토스 위젯을 띄우는 데 필요한 `client_key` 가 없다 → Task 6.
> `customer_name` 은 주석엔 `order.user.username` 이라 돼 있으나 실제로는 `order.recipient_name`
> (배송지 수령인) 을 쓴다 ([payment_service.py:92](../app/payment/payment_service.py#L92)).

### 2-3. [app/payment/payment_router.py](../app/payment/payment_router.py) — HTTP 엔드포인트

`prefix="/payments"` → 최종 경로 `/api/v1/payments/...`. [app/api/v1.py:57](../app/api/v1.py#L57) 에서 등록.

| 메서드 | 경로 | 인증 | 서비스 호출 | 성공 코드 |
|---|---|---|---|---|
| POST | `/payments/init` | `Depends(get_active_user)` | `init_payment(user.id, body)` | 201 |
| POST | `/payments/confirm` | `dependencies=[Depends(get_active_user)]` | `confirm_payment(body, background_tasks)` | 200 |
| POST | `/payments/webhooks/toss` | **없음** | `handle_webhook(body)` | 200 |

웹훅 라우터 ([payment_router.py:72](../app/payment/payment_router.py#L72)): 서명 검증 없음.
서비스가 `paymentKey` 로 토스에 되물어보므로 위조 body 로는 상태 변경 불가.
조회 실패 시 `PaymentGatewayUnknownError`(502) → 토스가 재시도.

### 2-4. [app/payment/payment_service.py](../app/payment/payment_service.py) — 비즈니스 로직 ★핵심

`PaymentService.__init__(repo, gateway, email_sender)` — 3개 협력자 주입.

#### `init_payment(user_id, req)` — [L58](../app/payment/payment_service.py#L58)
1. `get_order_by_number_with_lock` — **주문 행 FOR UPDATE 락** (READY 확인→생성 구간 원자화)
2. 소유권(`order.user_id == user_id`) + `status == PENDING` 확인 (아니면 예외)
3. 기존 READY Payment 있으면 재사용, 없으면 `Payment(status=READY)` 생성
4. `PaymentInitResponse` 반환

#### `confirm_payment(req, background_tasks)` — [L101](../app/payment/payment_service.py#L101)
1. `get_order_by_number` — 주문 조회 (없으면 `OrderNotFoundError`)
2. `order.status == PENDING` 확인 (타임아웃 취소된 주문 방어)
3. `get_by_order_id_with_lock` — **결제 목록 FOR UPDATE 락** (동시 confirm 이중 호출 방지)
4. READY Payment 없고 PAID 있으면 → **멱등 성공 반환** (gateway 재호출 안 함)
5. `req.amount == order.total_amount` 검증 (불일치 시 예외)
6. `gateway.confirm(payment_key, order_id, amount=order.total_amount)`
   — ⚠️ 전달 금액은 `req.amount` 가 아니라 **서버 신뢰값** `order.total_amount` (commit 040912b)
7. `update_status_paid(payment, result)` + `update_order_paid(order)`
8. `get_user_email` → 있으면 `BackgroundTasks` 에 결제완료 메일 등록
9. `PaymentConfirmResponse` 반환

예외 구분:
- `PaymentFailedError` (422) — PG 명시적 거절, 금액 불일치, READY 없음
- `PaymentGatewayUnknownError` (502) — 타임아웃/네트워크. **주문 PENDING 유지, 재시도 유도 금지**

#### `handle_webhook(payload)` — [L180](../app/payment/payment_service.py#L180)
1. `event_type != "PAYMENT_STATUS_CHANGED"` 면 무시
2. `data["paymentKey"]` 없으면 무시
3. **`gateway.get_payment(payment_key=...)`** — 토스에 실제 상태 재조회 (body 불신)
4. `get_by_pg_tid_with_lock(payment_key)` — **Payment 행 FOR UPDATE 락**
5. 없으면 `data["orderId"]` 로 `get_ready_payment_by_order_number_with_lock` fallback
   (confirm 전이라 pg_tid 가 아직 DB 에 없는 경우)
6. `_apply_remote_payment_status(payment, remote)` 호출

#### `_apply_remote_payment_status(payment, remote)` — [L216](../app/payment/payment_service.py#L216)

| `remote.status` | 처리 |
|---|---|
| `DONE` | Payment→PAID, `pg_tid` 채움. `paid_at is None`(웹훅이 confirm 보다 먼저)이면 카드 메타도 채움. Order PENDING→PAID |
| `CANCELED` | Payment→CANCELLED + `_restore_order_stock_and_cancel` |
| `PARTIAL_CANCELED` | Payment→PARTIAL_CANCELLED (재고 복구 안 함 — 라인별 정책 미정) |
| `ABORTED` / `EXPIRED` | Payment→FAILED, `fail_reason="토스 결제 상태: {status}"` + 재고 복구 + 주문 취소 |
| `READY` / `IN_PROGRESS` / `WAITING_FOR_DEPOSIT` | 무시 (로그만) — 확정 전 |

**PAID 인 결제에 도착한 웹훅**: `DONE` 재수신 → 멱등 무시. `CANCELED`/`PARTIAL_CANCELED` →
아래 취소 로직으로 통과. 그 외 → 경고 로그 + 무시.

#### `_restore_order_stock_and_cancel(order_id)` — [L266](../app/payment/payment_service.py#L266)
`get_order_by_id_with_lock` (**Order 행 락**) → 이미 CANCELLED 면 return(재고 이중 복구 방지)
→ 각 `order.items` 만큼 `increment_stock` → `order.status = CANCELLED`.

#### `_send_payment_confirmation_email(...)` — [L280](../app/payment/payment_service.py#L280)
모듈 함수 (self 없음). `BackgroundTasks` 로 실행. 카드 정보 있으면 "신한카드 1234 · 일시불" 형식.

### 2-5. [app/payment/adapters/ports.py](../app/payment/adapters/ports.py) — 외부 통합 인터페이스

`= 헥사고날 아키텍처의 포트. Service 는 SDK 를 직접 import 안 하고 이 Protocol 에만 의존.`

| 심볼 | 설명 |
|---|---|
| `TossConfirmResult` (dataclass) | `confirm()` 반환. `method, pg_tid, paid_at, card_company, card_last4, installment_months, approval_number` |
| `TossPaymentResult` (dataclass) | `get_payment()` 반환. 위 + `status`, `total_amount`, `balance_amount`(취소 가능 잔액) |
| `PaymentGateway` (Protocol) | `async confirm(*, payment_key, order_id, amount)`, `async get_payment(*, payment_key)` |

> `cancel()` 은 아직 이 Protocol 에 없다 → Task 3 에서 추가.

### 2-6. [app/payment/adapters/toss.py](../app/payment/adapters/toss.py) — 토스 REST 어댑터

- `_TOSS_API_BASE = "https://api.tosspayments.com/v1/payments"`
- `_auth_header()` — `settings.toss_secret_key` 없으면 `PaymentFailedError`.
  `Authorization: Basic base64(secretKey + ":")`
- `_parse_toss_datetime(raw)` — ISO-8601(`+09:00`/`Z`) → tz-aware `datetime`
- `TossPaymentGateway.confirm()`:
  - `POST /v1/payments/confirm` body `{paymentKey, orderId, amount}`
  - `httpx.TransportError` → `PaymentGatewayUnknownError`
  - status != 200 → `PaymentFailedError` (⚠️ 아직 `{code, message}` 파싱 안 함 — Task 5)
  - `approvedAt` 없으면 `PaymentFailedError`
- `TossPaymentGateway.get_payment()`:
  - `GET /v1/payments/{paymentKey}`
  - `TransportError` OR status != 200 → `PaymentGatewayUnknownError` (상태 불명 → 웹훅 재시도 유도)

### 2-7. [app/payment/adapters/fake.py](../app/payment/adapters/fake.py) — 개발용

`FakePaymentGateway` — `confirm`/`get_payment` 둘 다 항상 성공(`DONE`, 개발카드 0000).
`USE_FAKE_PG=true` 일 때 주입. 맨 아래 `_: PaymentGateway = FakePaymentGateway()` 로
import 시점에 Protocol 정합성 체크.

### 2-8. [app/payment/payment_repository.py](../app/payment/payment_repository.py) — DB 접근

`= Spring Data JPA Repository. 모든 쿼리를 여기 모은다. router 는 직접 호출 금지.`

| 메서드 | 락 | 용도 |
|---|---|---|
| `get_by_id` / `get_by_order_id` / `get_by_pg_tid` | — | 일반 조회 |
| `get_by_order_id_with_lock` | `FOR UPDATE` | confirm 동시 호출 방지 |
| `get_by_pg_tid_with_lock` | `FOR UPDATE` | 웹훅 동시 수신 방지 |
| `get_ready_payment_by_order_number(_with_lock)` | 선택 | 웹훅 pg_tid 없을 때 fallback |
| `get_order_by_number(_with_lock)` | 선택 | init 시 주문 락 |
| `get_order_by_id(_with_lock)` | 선택 | 웹훅 취소 시 주문+items 락 |
| `save` | — | `add` + `flush` + `refresh` (PK 할당). **commit 은 `deps.db_session` 에서** |
| `update_status_paid(payment, result)` | — | PAID 전환 + 메타 저장 + `flush` |
| `update_order_paid(order)` | — | Order → PAID + `paid_at` |
| `increment_stock(product_id, qty)` | — | 원자적 `UPDATE products SET stock = stock + :q`. SOLD_OUT→ACTIVE 자동 복원 |

> 트랜잭션 경계: 요청 1개 = 세션 1개 = 트랜잭션 1개. `db_session` 의존성이 요청 끝에
> `commit`/`rollback`. 서비스는 `flush` 만 하고 `commit` 안 한다 (= JPA `EntityManager` 패턴).

### 2-9. [app/core/deps.py:244](../app/core/deps.py#L244) — 와이어링

```python
async def get_payment_service(session=Depends(db_session), email_sender=Depends(get_email_sender)):
    if settings.use_fake_pg:
        gateway = FakePaymentGateway()
    else:
        gateway = TossPaymentGateway()
    return PaymentService(PaymentRepository(session), gateway, email_sender)
```

### 2-10. [app/core/config.py:73](../app/core/config.py#L73) — 환경변수

| 설정 | 기본값 | `.env` 키 | 비고 |
|---|---|---|---|
| `toss_secret_key` | `None` | `TOSS_SECRET_KEY` | 서버↔토스 Basic 인증 |
| `use_fake_pg` | `False` | `USE_FAKE_PG` | true 면 Fake 게이트웨이 |
| ~~`toss_client_key`~~ | — | `TOSS_CLIENT_KEY` | **코드에 필드 없음.** `.env.example` 엔 존재 → Task 6 |

### 2-11. [app/payment/ports.py](../app/payment/ports.py) — ⚠️ DEAD CODE

`PaymentInitResult` / `PaymentVerifyResult` / 옛 `PaymentGateway`(cancel·verify_webhook_signature
포함). **어디서도 import 안 됨.** `adapters/ports.py` 와 이름이 겹쳐 헷갈림.
Task 3 에서 `cancel` 만들 때 이 파일 삭제 검토.

---

## 3. 상태 머신

### PaymentStatus

```
        init_payment
           │
           ▼
        READY ──confirm(DONE)──► PAID ──웹훅(CANCELED)──► CANCELLED
           │                      │
           │                      └───웹훅(PARTIAL_CANCELED)──► PARTIAL_CANCELLED
           │
           └──웹훅(ABORTED/EXPIRED)──► FAILED
```

### OrderStatus (결제 관련 구간만)

```
PENDING ──confirm 성공 / 웹훅 DONE──► PAID ──► PREPARING ──► SHIPPING ──► DELIVERED
   │                                   │                                    │
   │  30분 방치 → _expire_if_abandoned  │  cancel_order                      │  request_refund
   ▼                                   ▼                                    ▼
CANCELLED ◄──────웹훅 ABORTED/EXPIRED/CANCELED──────┘                     REFUNDED
```

- `PENDING` 만료: [order_service._expire_if_abandoned](../app/order/order_service.py#L249) —
  주문 조회 시 지연 평가로 30분 초과 PENDING 을 즉시 취소 + 재고 복구
- `_CANCELLABLE_STATUSES = {PENDING, PAID, PREPARING}` ([order_service.py:45](../app/order/order_service.py#L45))

---

## 4. 동시성 / 멱등성 설계

경쟁 시나리오와 방어 장치:

| 시나리오 | 방어 |
|---|---|
| 사용자가 `init` 을 더블클릭 | `get_order_by_number_with_lock` — 주문 행 락으로 READY 중복 생성 차단 |
| `confirm` 이 동시에 2번 (재시도 + 원클릭) | `get_by_order_id_with_lock` — 두 번째는 이미 PAID 를 보고 멱등 반환. `gateway.confirm` 은 1회만 |
| 토스 웹훅 재전송(동일 이벤트 2번) | `get_by_pg_tid_with_lock` — 두 번째는 이미 확정 상태 보고 무시 |
| 웹훅 취소가 동시 도착 → 재고 이중 복구 | `_restore_order_stock_and_cancel` 이 `get_order_by_id_with_lock` 후 `status == CANCELLED` 조기 반환 |
| confirm 과 웹훅(DONE) 이 레이스 | 둘 다 Payment/Order 행 락 경쟁 → 나중 것이 이미 PAID 확인 후 멱등 처리 |

이 시나리오들은 [tests/integration/test_payment_service.py](../tests/integration/test_payment_service.py)
에서 실제 Postgres + `asyncio.gather` 로 검증한다.

**멱등성 키**: `payments.pg_tid` 의 `UNIQUE` 제약. 같은 `paymentKey` = 같은 결제.

---

## 5. DB 스키마

`payments` 테이블은 [alembic/versions/e9bcd41ab78f_init_schema.py:151](../alembic/versions/e9bcd41ab78f_init_schema.py#L151) 에서 생성.

```sql
CREATE TABLE payments (
  id BIGINT GENERATED ... PRIMARY KEY,
  order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
  pg_provider VARCHAR(20) NOT NULL,
  pg_tid VARCHAR(100) UNIQUE,                      -- 멱등성 키
  method VARCHAR(20) NOT NULL,
  amount INTEGER NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'READY'
    CHECK (status IN ('READY','PAID','CANCELLED','PARTIAL_CANCELLED','FAILED')),
  paid_at TIMESTAMPTZ, cancelled_at TIMESTAMPTZ,
  fail_reason VARCHAR(500),
  card_company VARCHAR(30), card_last4 VARCHAR(4),
  installment_months INTEGER, approval_number VARCHAR(50),
  created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ
);
CREATE INDEX ix_payments_order_id ON payments(order_id);
```

- Enum 은 `native_enum=False` → Postgres 네이티브 ENUM 이 아니라 `VARCHAR + CHECK`.
  값 추가(`WAITING_FOR_DEPOSIT` 등) 시 마이그레이션으로 CHECK 제약 갱신 필요.
- `alembic upgrade head` 미적용 환경 주의 (todo.md 후속조치 참고).

---

## 6. 테스트 맵

| 파일 | 유형 | 커버 |
|---|---|---|
| [tests/test_payment_service.py](../tests/test_payment_service.py) | 단위 | `PaymentService` 전체. `_FakeGateway`(status 파라미터화) + `_FakePaymentRepo` |
| [tests/test_toss_adapter.py](../tests/test_toss_adapter.py) | 단위 | `TossPaymentGateway.confirm` / `get_payment` — `unittest.mock.patch` 로 `httpx.AsyncClient` 교체 |
| [tests/integration/test_payment_service.py](../tests/integration/test_payment_service.py) | 통합 | 실 Postgres 동시성 (웹훅 재전송, 동시 confirm, 레이스) |
| [tests/integration/test_payment_repository.py](../tests/integration/test_payment_repository.py) | 통합 | 리포지토리 쿼리 정확성 |

실행:
```bash
.venv/bin/pytest tests/test_payment_service.py tests/test_toss_adapter.py -v   # 단위
docker compose up -d postgres && .venv/bin/pytest tests/integration/test_payment_service.py -v
```

현재 483 passed / ruff 0 / mypy 0.

---

## 7. 아직 mock / 미완성인 것 (중요)

1. **프론트엔드 결제 미연동** — `rekle/src/views/checkout/OrderView.vue` 의 `pay()` 는
   `orders.create()` 후 바로 `/checkout/complete` 로 이동. `/payments/init`·`/confirm`
   호출 없음. 토스 위젯 SDK 로딩도 없음. API 클라이언트(`rekle/src/api/admin/payments.ts`)는
   존재하지만 **buyer 플로우에 연결 안 됨** (경로도 `api/admin/` 아래라 위치가 이상함).
   → 결제는 지금 "주문서 = 계좌이체 무통장입금" 문구만 있고 실제 PG 를 안 탄다.
2. **PG 취소/환불 실호출 없음** — §1-3 참고. Task 3·4.
3. **토스 실제 계약 / 키** — `.env` 비어 있고 `USE_FAKE_PG` 만 true. Task 6.
4. **confirm 실패 사유 미저장** — 토스 `{code, message}` 무시. `Idempotency-Key` 헤더 없음. Task 5.
5. **가상계좌(계좌이체)** — `WAITING_FOR_DEPOSIT` 상태·`DEPOSIT_CALLBACK` 처리·환불계좌
   입력 전부 없음. 주문서 UI 는 "계좌이체"라고 써있지만 백엔드 흐름은 카드 기준.
6. **웹훅 IP 화이트리스트** — 없음. 현재는 "조회 재확인"만으로 방어.
7. **`docs/api.md` §10** — 옛 설계 문서. `/payments/verify`(→실제 `/confirm`),
   `data` envelope, `PENDING_PAYMENT`(→`PENDING`), `method: "card"`(→`CARD`) 등 불일치.
   실제 스펙은 이 문서 §2 를 신뢰.

---

## 8. 토스페이먼츠 참고 문서

### 8-1. 우리가 쓰는 API — 상세

#### 결제 승인 (confirm) — `TossPaymentGateway.confirm`
- 문서: https://docs.tosspayments.com/reference#결제-승인
- `POST https://api.tosspayments.com/v1/payments/confirm`
- 헤더: `Authorization: Basic {base64(secretKey + ":")}`, `Content-Type: application/json`,
  `Idempotency-Key: {고유값}` (← 우리 아직 안 붙임)
- body: `{ "paymentKey": str(≤200), "orderId": str(6~64), "amount": number }`
- 성공(200): `status="DONE"`, `method="카드"`(한글), `approvedAt`(ISO8601 `+09:00`),
  `totalAmount`, `balanceAmount`, `card: { issuerCode, number(마스킹), installmentPlanMonths, approveNo }`,
  `virtualAccount: {...}`(가상계좌)
- 실패: HTTP 4xx/5xx + `{ "code": "...", "message": "...(≤510)" }`

#### 결제 조회 (get_payment) — `TossPaymentGateway.get_payment` ★웹훅 검증에 사용
- 문서: https://docs.tosspayments.com/reference#결제-조회
- `GET https://api.tosspayments.com/v1/payments/{paymentKey}`
  또는 `GET /v1/payments/orders/{orderId}`
- 헤더: `Authorization: Basic ...`
- 응답: `Payment` 객체 전체 — `status`(8종), `method`, `totalAmount`, `balanceAmount`,
  `approvedAt`(nullable), `card`(nullable), `cancels[]`, `cashReceipts[]`

`Payment.status` 8종:
| 값 | 의미 |
|---|---|
| `READY` | 결제 생성 초기 |
| `IN_PROGRESS` | 결제수단 인증 완료 |
| `WAITING_FOR_DEPOSIT` | 가상계좌 입금 대기 |
| `DONE` | 승인 완료 |
| `CANCELED` | 승인 후 전액 취소 |
| `PARTIAL_CANCELED` | 부분 취소 |
| `ABORTED` | 승인 실패 |
| `EXPIRED` | 유효시간(30분) 경과 |

#### 결제 취소 (cancel) — ❌ 미구현, Task 3
- 문서: https://docs.tosspayments.com/reference#결제-취소
- `POST /v1/payments/{paymentKey}/cancel`
- 헤더: `Authorization: Basic ...`, `Idempotency-Key: {고유값}`
- body: `{ "cancelReason": str(≤200, 필수), "cancelAmount": number|null(null=전액),
  "refundReceiveAccount": {bank, accountNumber, holderName}(가상계좌 필수), "taxFreeAmount": number }`
- 응답: `Payment` 객체, `cancels[]` 배열에 취소건별 `transactionKey`, `cancelAmount`, `canceledAt`

### 8-2. 웹훅
- 문서: https://docs.tosspayments.com/guides/v2/webhook ,
  https://docs.tosspayments.com/reference/using-api/webhook-events
- **결제 웹훅에는 서명이 없다.** `tosspayments-webhook-signature` 헤더는
  `payout.changed`·`seller.changed`(지급대행) 전용. → body 불신, 조회 API 로 재확인.
- 이벤트 종류: `PAYMENT_STATUS_CHANGED`(우리가 처리), `DEPOSIT_CALLBACK`(가상계좌 입금),
  `CANCEL_STATUS_CHANGED`(해외 간편결제), `METHOD_UPDATED`, `CUSTOMER_STATUS_CHANGED`,
  `payout.changed`, `seller.changed`, `BILLING_DELETED`, `ORDER_PAYMENT_STATUS_CHANGED`,
  `ars-reservation.changed`
- 재시도: 200 을 10초 내에 못 받으면 최대 7회, 약 3일 19시간에 걸쳐 지수 백오프
- `PAYMENT_STATUS_CHANGED` body: `{ eventType, createdAt, data: <Payment 객체> }`
- 등록: 개발자센터 → 웹훅 → URL `https://{도메인}/api/v1/payments/webhooks/toss` + 이벤트 선택

### 8-3. 프론트 위젯 (프론트 작업 시)
- 결제위젯 연동: https://docs.tosspayments.com/guides/v2/payment-widget/integration
- `clientKey` 로 위젯 로드 → `requestPayment({ orderId, orderName, amount, successUrl, failUrl })`
- success 리다이렉트: `?paymentKey=...&orderId=...&amount=...` → 프론트가 이 값으로
  `POST /payments/confirm` 호출
- 테스트 키·테스트 카드: https://docs.tosspayments.com/reference/test-and-development
- 에러 코드 전체: https://docs.tosspayments.com/reference/error-codes

### 8-4. MCP 문서 검색 서버
`tosspayments-integration-guide` (이미 `claude mcp add` 됨). 세션 재시작 후
자연어로 "가상계좌 웹훅 처리 방법" 처럼 물으면 공식 문서를 검색. **API 실행은 안 함.**

### 8-5. LLM/AI 연동 가이드 (토스 공식)
- https://docs.tosspayments.com/guides/v2/get-started/llms-guide
- https://toss.tech/article/tosspayments-mcp

---

## 9. 용어집 — 헷갈리는 식별자

| 용어 | 정체 | 어디서 |
|---|---|---|
| `paymentKey` | 토스가 발급하는 결제 거래 ID | 토스 위젯 success 콜백, confirm/조회/취소 API |
| `pg_tid` | 위 `paymentKey` 를 우리 DB `payments` 에 저장한 컬럼명 | `payments.pg_tid` (멱등성 키) |
| `orderId` (토스 용어) | 가맹점이 정하는 주문 식별자 = 우리 `order_number` | confirm body, 웹훅 data |
| `order_number` | `RK-YYMMDD####` 사람이 읽는 주문번호 (Order PK 와 별개) | `orders.order_number` |
| `PaymentConfirmRequest.order_id` | 필드명은 `order_id` 지만 값은 `order_number` (토스 명명 따름) | [payment_schemas.py:37](../app/payment/payment_schemas.py#L37) |
| `amount` (confirm) | 프론트가 보낸 값. **검증용으로만** 쓰고 실제 승인엔 `order.total_amount` 전달 | [payment_service.py:152](../app/payment/payment_service.py#L152) |
| `clientKey` / `secretKey` | 토스 API 키 쌍. client=프론트 위젯용(공개), secret=서버용(비밀) | `.env` |
| `balanceAmount` | 토스 결제의 취소 가능 잔액. 0 이면 전액 취소됨 | `TossPaymentResult.balance_amount` |
