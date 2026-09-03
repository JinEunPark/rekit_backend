# 토스페이먼츠 실연동 작업 가이드

> 작성: 2026-08-31, 갱신: 2026-09-04. Fake 게이트웨이 → 토스 실연동 전환.
> Task 1~4 완료(웹훅 재확인 + 취소/환불). 남은 건 Task 5(confirm 하드닝)·6(정리)·7(가상계좌, 선택)·프론트.
> 각 Task 는 "왜 → 뭘 바꾸나 → 어떻게 검증 → 완료 기준" 4단으로 구성.
> TDD 원칙(CLAUDE.md §TDD): 테스트 먼저(Red) → 최소 구현(Green) → 정리(Refactor).
>
> **결제 모듈 전체를 먼저 이해하려면 → [payment_dev_state.md](payment_dev_state.md)** (코드 맵·플로우·상태머신·토스 문서 총정리).

---

## 0. 지금 상황 한눈에

결제 플로우 **골격은 이미 다 있고**, 본인 계정 토스 테스트 키로 실제 토스 API 를 호출한다
(2026-09-04 `FakePaymentGateway`/`use_fake_pg` 제거 — 항상 실 토스). 남은 건:

| # | 막힌 것 | 성격 | 상태 |
|---|---|---|---|
| A | 토스 실제 키 | 콘솔 작업 | ✅ 2026-09-04 본인 계정 테스트 키(`test_gsk_*`) `.env` 반영 |
| B | ~~웹훅 검증이 존재하지 않는 스펙으로 구현돼 있음~~ → **재조회 방식으로 교체** (Task 1·2) | 코드 수정 | ✅ 2026-08-31 |
| C | ~~주문 취소/환불 시 PG `cancel` 을 안 부름~~ → **`cancel()` 구현 + order/admin 연결** (Task 3·4) | 코드 신규 | ✅ 2026-09-04 |

**남은 것**: Task 5(confirm 하드닝) · Task 6(dead code 정리 + api.md §10.1/§10.2) · 프론트 위젯 마무리 ·
웹훅 URL/도메인 등록. **가상계좌는 안 함**(2026-09-04). 부분취소 재고 정책 미정.

나머지(모델, 스키마, 라우터, confirm 호출, 멱등성, 재고 복구)는 만들어져 있으니
**갈아엎지 말고 보강**하는 방향이다.

---

## 1. 코드 지도 — 먼저 읽어야 할 파일

읽는 순서대로 정렬했다. 각 파일이 "무슨 역할"이고 "지금 상태"가 어떤지.

| 순서 | 파일 | 역할 | 지금 상태 |
|---|---|---|---|
| 1 | [app/payment/models.py](../app/payment/models.py) | `Payment` 테이블, `PaymentStatus`/`PaymentMethod`/`PgProvider` enum | ✅ 완성. `PaymentStatus` 에 `WAITING_FOR_DEPOSIT` 없음(가상계좌 하면 추가) |
| 2 | [app/payment/adapters/ports.py](../app/payment/adapters/ports.py) | `PaymentGateway` **Protocol**(인터페이스) + `TossConfirmResult`/`TossPaymentResult` DTO | ✅ `confirm` + `get_payment` 있음. `cancel` 은 Task 3 |
| 3 | [app/payment/adapters/toss.py](../app/payment/adapters/toss.py) | 토스 REST API 실제 호출 어댑터 | ✅ `confirm`(보강은 Task 5) + `get_payment` + `cancel` 구현됨 |
| 4 | ~~app/payment/adapters/fake.py~~ | 개발용 항상성공 어댑터 | ❌ 2026-09-04 삭제 (테스트 키 사용) |
| 5 | [app/payment/payment_service.py](../app/payment/payment_service.py) | 결제 비즈니스 로직 (init / confirm / webhook / cancel_payment) | ✅ 웹훅 조회 재확인 + `cancel_payment` 추가 |
| 6 | [app/payment/payment_router.py](../app/payment/payment_router.py) | `/payments/init`, `/confirm`, `/webhooks/toss` | ✅ 서명 체크 제거, `handle_webhook` 위임만 |
| 7 | [app/payment/payment_schemas.py](../app/payment/payment_schemas.py) | 요청/응답 Pydantic DTO | ✅ 완성 (clientKey 는 프론트 전용이라 불필요) |
| 8 | [app/payment/payment_repository.py](../app/payment/payment_repository.py) | DB 접근 (락, 멱등 조회, 재고 복구) | ✅ `update_status_cancelled` 추가됨 |
| 9 | [app/core/deps.py](../app/core/deps.py) `get_payment_service` / `get_order_service` / `get_admin_order_service` | 게이트웨이·서비스 와이어링 | ✅ 항상 `TossPaymentGateway`, order/admin 에 payment_service 주입 |
| 10 | [app/core/config.py](../app/core/config.py) | `toss_secret_key` | ✅ `use_fake_pg` 제거됨 |
| 11 | [app/order/order_service.py](../app/order/order_service.py) `request_refund` / `cancel_order` | 사용자 주문 취소·환불 | ✅ PAID/PREPARING/DELIVERED 면 `cancel_payment` 호출 |
| 12 | [app/order/admin_order_service.py](../app/order/admin_order_service.py) `cancel_order` | 관리자 주문 취소 | ✅ 동일 |

### 테스트 파일

| 파일 | 커버 |
|---|---|
| [tests/test_toss_adapter.py](../tests/test_toss_adapter.py) | `TossPaymentGateway.confirm` — `unittest.mock.patch` 로 `httpx.AsyncClient` 교체하는 패턴. **이 패턴을 그대로 재사용** |
| [tests/test_payment_service.py](../tests/test_payment_service.py) | `PaymentService` 단위 — 모듈 로컬 `_FakePaymentRepo` + `_FakeGateway` (테스트 픽스처, 앱 어댑터 아님) |
| [tests/integration/test_payment_service.py](../tests/integration/test_payment_service.py) | 실제 Postgres 대상 |
| [tests/integration/test_payment_repository.py](../tests/integration/test_payment_repository.py) | 리포지토리 쿼리 |

---

## 2. 확인해야 할 외부 소스

### 토스페이먼츠 공식 문서 (필수)

| 주제 | URL | 왜 봐야 하나 |
|---|---|---|
| 결제 승인(confirm) | https://docs.tosspayments.com/reference#결제-승인 | Task 5 — 응답 필드, 실패 `{code, message}` |
| 결제 취소(cancel) | https://docs.tosspayments.com/reference#결제-취소 | Task 3 — body 필드, 부분취소, 멱등키 |
| 결제 조회 | https://docs.tosspayments.com/reference#결제-조회 | Task 1 — 웹훅 후 재조회에 사용 |
| 웹훅 이벤트 | https://docs.tosspayments.com/reference/using-api/webhook-events | Task 1·2 — 이벤트 종류, status 값, 서명 |
| 웹훅 연결 가이드 | https://docs.tosspayments.com/guides/v2/webhook | Task 1 — 등록 방법, 재시도 정책 |
| 테스트/키 관리 | https://docs.tosspayments.com/reference/test-and-development | Task 6 — 테스트 키 발급, 테스트 카드 |
| 에러 코드 | https://docs.tosspayments.com/reference/error-codes | Task 5 — `fail_reason` 에 뭘 담을지 |
| 결제위젯 SDK(프론트) | https://docs.tosspayments.com/guides/v2/payment-widget/integration | 프론트가 `client_key` 로 위젯 띄우는 흐름 (백엔드가 뭘 내려줘야 하는지) |

### 토스 MCP 서버 (문서 검색용, 이미 추가됨)

```
tosspayments-integration-guide  (claude mcp list 로 확인)
```
이 세션 재시작(또는 `/mcp`) 후 자연어로 "웹훅 서명 검증 방법 알려줘" 처럼 물어보면
공식 문서를 검색해준다. **API 를 실행하진 않고 문서만 검색**한다.

### 우리 저장소 문서

- [docs/api.md](api.md) — 결제 API 스펙 (§1.7 부근)
- [docs/todo.md](todo.md) — 3번째 항목 "[결제] Toss Payments 실키 발급/설정"
- [docs/요구사항정의서.md](요구사항정의서.md) — 결제/환불 정책

---

## 3. 스펙 확인 결과 (2026-08-31 조사 — 다시 안 찾아도 됨)

### 3-1. confirm (`POST /v1/payments/confirm`)
- 헤더: `Authorization: Basic base64(secretKey + ":")`, `Idempotency-Key: {고유값}`
- body: `{ paymentKey, orderId, amount }`
- 성공: `status="DONE"`, `method="카드"`(한글!), `approvedAt`(ISO8601 +09:00),
  `totalAmount`, `card.{issuerCode, number(마스킹), installmentPlanMonths, approveNo}`,
  가상계좌면 `virtualAccount` 객체
- 실패: HTTP 4xx/5xx + body `{ "code": "...", "message": "..." }`

### 3-2. cancel (`POST /v1/payments/{paymentKey}/cancel`)
- 헤더: `Authorization: Basic`, `Idempotency-Key`
- body: `cancelReason`(필수, ≤200자), `cancelAmount`(생략 시 전액),
  가상계좌 환불이면 `refundReceiveAccount` 필수
- 성공: `Payment` 객체 반환, `cancels[]` 배열에 취소건별 `transactionKey`

### 3-3. 웹훅 — ⚠️ 여기가 현재 코드의 핵심 오류
- **결제 웹훅(`PAYMENT_STATUS_CHANGED`, `DEPOSIT_CALLBACK`, `CANCEL_STATUS_CHANGED`)
  에는 HMAC 서명 헤더가 없다.** `tosspayments-webhook-signature` 는
  지급대행(`payout.changed`, `seller.changed`) 이벤트 전용 — 우리는 안 씀.
- 따라서 현재 [toss.py](../app/payment/adapters/toss.py) 의
  `HMAC-SHA256(secret_key, body).hexdigest()` 검증과
  [payment_router.py](../app/payment/payment_router.py) 의 `TossPayments-Signature`
  헤더 읽기는 **존재하지 않는 스펙**. 지우거나 교체해야 한다.
- 토스 공식 권장 위변조 방지: **웹훅 body 를 신뢰하지 말고, 받자마자
  결제 조회 API 로 재확인** — `GET /v1/payments/{paymentKey}` 또는
  `GET /v1/payments/orders/{orderId}` 를 호출해 그 응답의 `status` 로 상태 전환.
- 결제 조회(`GET /v1/payments`) 응답의 `status` 값 8종:
  `READY / IN_PROGRESS / WAITING_FOR_DEPOSIT / DONE / CANCELED / PARTIAL_CANCELED / ABORTED / EXPIRED`
  (`balanceAmount` = 취소 가능 잔액. 0 이면 전액 취소됨)
  → `handle_webhook` 은 이 조회 결과의 status 로만 전이한다 (웹훅 body 의 status 는 무시)
- `DEPOSIT_CALLBACK`(가상계좌 입금): body 의 `secret` 을 승인 응답의
  `virtualAccount.secret` 과 대조해서 검증

---

## 4. 작업 순서

> 의존도 순서. Task 1·2 는 세트(웹훅), Task 3·4 도 세트(취소).
> 각 Task 는 1일치 분량으로 쪼갬. **Task 시작 시 이 문서와 CLAUDE.md 를 같이 열 것.**

### ✅ Task 1 — 웹훅 검증을 "재조회 방식"으로 교체 (2026-08-31 완료)

**한 일**:
1. `adapters/ports.py`: `verify_webhook_signature` 제거, `TossPaymentResult` DTO +
   `async get_payment(*, payment_key)` 추가
2. `adapters/toss.py`: HMAC 서명 코드/`hmac`·`hashlib` import 삭제, `get_payment` 구현
   (`GET /v1/payments/{paymentKey}`, Basic 인증, 실패 시 `PaymentGatewayUnknownError`).
   `_auth_header()` / `_parse_toss_datetime()` 헬퍼로 정리
3. `adapters/fake.py`: `get_payment` 추가 (항상 `DONE`)
4. `payment_router.py`: `Request`/`TossPayments-Signature`/`verify_webhook` 제거 —
   `handle_webhook` 위임만
5. `payment_service.py`: `verify_webhook` 제거. `handle_webhook` 이 `paymentKey` 로
   `gateway.get_payment()` 호출 → 실제 상태(`remote.status`)로만 전이.
   전이 로직은 `_apply_remote_payment_status()` 로 분리

**후속(미완)**: 토스 웹훅 발신 IP 화이트리스트 미들웨어는 아직 없음.
현재는 "조회 재확인"만으로 방어 (위조 body 로는 상태 변경 불가하나, 유효 paymentKey 를
아는 공격자가 조회 API 호출을 유발할 수는 있음 — rate 는 토스 재시도 정책으로 제한적).

---

### ✅ Task 2 — 웹훅 status 값을 실제 스펙에 맞추기 (2026-08-31 완료)

**한 일** — `payment_service.py`:
- 결제 조회 status 8종 전부 처리:
  `DONE`→PAID / `CANCELED`→취소+재고복구 / `PARTIAL_CANCELED`→`PARTIAL_CANCELLED`(재고 스킵) /
  `ABORTED`·`EXPIRED`→FAILED+취소+재고복구 / `READY`·`IN_PROGRESS`·`WAITING_FOR_DEPOSIT`→무시
- `_TOSS_EXPIRED` 상수 + `_TOSS_PENDING_STATUSES` frozenset 추가
- 부분취소는 `PaymentStatus.CANCELLED` → `PARTIAL_CANCELLED` 로 정정 (모델에 이미 있던 값)
- `payment.fail_reason` = `"토스 결제 상태: {status}"`
- 웹훅이 confirm 보다 먼저 도착한 경우(`paid_at is None`) 카드 메타도 조회 결과로 채움

**검증**: `tests/test_payment_service.py` 웹훅 테스트 전면 갱신 + 신규 4건
(`test_webhook_ignores_body_status_and_uses_gateway_refetch`,
`test_webhook_expired_...`, `test_webhook_in_progress_status_is_ignored`,
`test_webhook_propagates_gateway_unknown_error_when_refetch_fails`).
`tests/test_toss_adapter.py` 에 `get_payment` 3건. 483 passed / ruff 0 / mypy 0.

> ⚠️ 남은 dead code: [app/payment/ports.py](../app/payment/ports.py) (넓은 인터페이스,
> 어디서도 import 안 됨)에 아직 옛 `verify_webhook_signature`/`cancel` 시그니처가 있음.
> Task 3 에서 `cancel` 을 만들 때 이 파일을 삭제할지 결정할 것.

---

### ✅ Task 3 — `TossPaymentGateway.cancel()` 구현 (2026-09-04 완료)

**한 일**:
1. `adapters/ports.py`: `TossCancelResult` DTO(`status`, `cancelled_amount`,
   `balance_amount`, `transaction_key`) + `async cancel(*, payment_key, reason, cancel_amount=None)`
   Protocol 에 추가
2. `adapters/toss.py`: `cancel` 구현 — `POST /v1/payments/{payment_key}/cancel`,
   `Idempotency-Key: cancel-{payment_key}-{amount|'full'}` 헤더, body `{cancelReason, cancelAmount?}`.
   4xx → `_raise_toss_failure()` 헬퍼로 `{code, message}` 담아 `PaymentFailedError`,
   네트워크 → `PaymentGatewayUnknownError`
3. `adapters/fake.py`: `cancel` 추가
4. `_raise_toss_failure()` 는 confirm 에도 재사용 가능하게 만들어둠 (Task 5 에서 적용)

**검증**: `tests/test_toss_adapter.py` 6건 (`test_cancel_full_calls_api_with_reason`,
`test_cancel_partial_passes_cancel_amount`, `test_cancel_sends_idempotency_key_header`,
`test_cancel_4xx_raises_payment_failed_with_toss_message`, `test_cancel_network_error_...`).

> confirm 자체의 `Idempotency-Key` 헤더는 Task 5 로 이월 (cancel 만 우선).

---

### ✅ Task 4 — 주문 취소/환불에서 PG cancel 호출 연결 (2026-09-04 완료)

**한 일**:
1. `payment_service.py` `cancel_payment(order_id, *, reason, cancel_amount=None)`:
   `get_by_order_id_with_lock` 로 PAID Payment 조회 → 없으면 멱등 return(결제 전/이미 취소) →
   `pg_tid` 없으면 `PaymentFailedError` → `gateway.cancel()` → `repo.update_status_cancelled()`
2. `payment_repository.py` `update_status_cancelled(payment, result)`:
   `PARTIAL_CANCELED` 또는 잔액>0 이면 `PARTIAL_CANCELLED`, 아니면 `CANCELLED` + `cancelled_at`
3. `order_service.py`: `OrderService(repo, payment_service=None)` 로 주입(옵션).
   `cancel_order` — `order.status in {PAID, PREPARING}` 면 `cancel_payment()` 먼저 (실패 시 롤백).
   `request_refund` — DELIVERED 면 `cancel_payment()` 후 REFUNDED. PENDING 은 PG 호출 없음
4. `admin_order_service.py` `cancel_order` — 동일, `body.reason` 을 취소 사유로 전달
5. `deps.py`: `get_order_service` / `get_admin_order_service` 가 `get_payment_service` 를 주입.
   (같은 `db_session` 공유 → 한 트랜잭션. order → payment **서비스** 호출만, repo 직접 호출 X)

**검증**: `test_payment_service.py` 5건(cancel_payment), `test_order_service.py` 5건
(cancel/refund ↔ PG 연동 + PG 실패 시 롤백), `test_admin_order_service.py` 3건.
502 passed / ruff 0 / mypy 0.

> **부분취소 재고 정책은 여전히 미정** — `cancel_amount` 경로는 어댑터·서비스에 있지만
> order/admin 라우터는 전액 취소만 호출한다. 부분취소 시 라인별 재고 복구는 TODO.

---

### Task 5 (남음) — confirm 응답 파싱 하드닝

- `adapters/toss.py` `confirm`: status != 200 일 때 `_raise_toss_failure(resp, "Toss confirm 실패")`
  로 교체 (이미 `cancel` 이 쓰는 헬퍼. `{code, message}` 를 담아 `PaymentFailedError`)
- `payment_service.confirm_payment`: 이 에러를 잡아 `payment.fail_reason` 저장 + `status=FAILED`
- `confirm` 에 `Idempotency-Key: confirm-{payment_key}` 헤더 (cancel 은 이미 있음)
- `test_toss_adapter.py`: `test_confirm_4xx_includes_toss_error_code`,
  `test_confirm_sends_idempotency_key_header`

### Task 6 (남음) — 정리

1. dead code [app/payment/ports.py](../app/payment/ports.py) 삭제 (미사용)
2. `docs/api.md` §10.1(결제 초기화)·§10.2(결제 검증) 를 실제 구현에 맞게 재작성
   (`/verify`→`/confirm`, `data` envelope 제거, `PENDING_PAYMENT`→`PENDING`, `method: "card"`→`CARD`)

### 운영 (콘솔)

- ✅ 본인 계정 테스트 키 발급 → 백엔드 `.env` `TOSS_SECRET_KEY`, 프론트 `.env.local` `VITE_TOSS_CLIENT_KEY`
- [ ] 개발자센터 → 웹훅 URL `https://{도메인}/api/v1/payments/webhooks/toss` 등록 (`PAYMENT_STATUS_CHANGED`)
- [ ] 결제창 허용 도메인 등록
- [ ] 오픈: 전자결제 심사 완료 후 `live_gsk_*` / `live_gck_*` 로 교체

### end-to-end 검증 (프론트 위젯 마무리 후)

토스 테스트 카드로 실제 결제창 → confirm → `payments` 테이블 `PAID` → 주문 취소 → `CANCELLED` +
토스 개발자센터 결제내역에서 승인/취소 확인.

---

### ~~Task 7 — 가상계좌~~ (2026-09-04 안 하기로 결정)

가상계좌(입금대기) **미지원**. 대신 `confirm` 이 토스 응답 `status != "DONE"` 이면 거절한다
([toss.py](../app/payment/adapters/toss.py) — 입금 전 주문 확정 방지). 프론트 위젯도
가상계좌 결제수단을 노출하지 않는다.
※ 실시간 계좌이체(`method` = BANK, 즉시 `DONE`)는 카드와 동일하게 처리되므로 그대로 사용 가능.

---

### Task 8 — 마무리 점검

- [ ] `.venv/bin/pytest -v` — 실패 0
- [ ] `.venv/bin/ruff check app tests` — 0
- [ ] `.venv/bin/mypy app` — 0
- [ ] 변경 파일 라인 커버리지 ≥ 80% (`--cov=app --cov-report=term-missing`)
- [ ] `docs/api.md` 결제 섹션 최신화 (웹훅 검증 방식, 취소 API)
- [ ] `docs/todo.md` 관련 항목 체크
- [ ] `docs/runbook.md` 에 "웹훅 미수신 / 결제 실패 / 취소 실패" 대응 절차 (Week 7 항목)

---

## 5. 아직 정해야 할 것

- **부분취소 재고 정책** — `cancel_amount` 경로는 어댑터·서비스에 이미 있으나
  order/admin 라우터는 전액 취소만 호출. 부분취소 시 라인별 재고 복구를 어떻게 할지 미정.
  (당장은 전액만 노출하면 결정 미룰 수 있음)

> ~~가상계좌~~ — 2026-09-04 안 하기로 결정 (Task 7 참고).

---

## 6. 자주 쓸 명령

```bash
# 어댑터 테스트만
.venv/bin/pytest tests/test_toss_adapter.py -v

# 결제 서비스 + 어댑터
.venv/bin/pytest tests/test_payment_service.py tests/test_toss_adapter.py -v

# 통합 (Postgres 필요)
docker compose up -d postgres redis
.venv/bin/pytest tests/integration/test_payment_service.py -v

# 완료 게이트
.venv/bin/pytest -q && .venv/bin/ruff check app tests && .venv/bin/mypy app

# 로컬 서버 (백엔드 .env 에 TOSS_SECRET_KEY=test_gsk_* 필요, 없으면 결제 호출 시 에러)
.venv/bin/uvicorn app.main:app --reload

# MCP 문서 검색 서버 확인
claude mcp list
```
