# 토스페이먼츠 실연동 작업 가이드

> 작성: 2026-08-31 세션. Fake 게이트웨이 → 토스 실연동으로 전환하기 위해
> **하루에 Task 하나씩** 진행할 수 있게 정리한 문서.
> 각 Task 는 "왜 → 뭘 바꾸나 → 어떻게 검증 → 완료 기준" 4단으로 구성.
> TDD 원칙(CLAUDE.md §TDD): 테스트 먼저(Red) → 최소 구현(Green) → 정리(Refactor).
>
> **결제 모듈 전체를 먼저 이해하려면 → [payment_dev_state.md](payment_dev_state.md)** (코드 맵·플로우·상태머신·토스 문서 총정리).

---

## 0. 지금 상황 한눈에

결제 플로우 **골격은 이미 다 있고**, `USE_FAKE_PG=true` 인 `FakePaymentGateway` 로
init → confirm → webhook 이 end-to-end 로 동작한다. 실연동을 막는 건 딱 3가지:

| # | 막힌 것 | 성격 | 상태 |
|---|---|---|---|
| A | 토스 실제 키 없음 (`.env` 비어 있음, `USE_FAKE_PG=true`) | 콘솔 작업 | Task 6 |
| B | ~~웹훅 검증이 존재하지 않는 스펙으로 구현돼 있음~~ → **재조회 방식으로 교체 완료** (Task 1·2) | 코드 수정 | ✅ 2026-08-31 |
| C | 주문 취소/환불 시 PG `cancel` 을 안 부름 (상태만 바꿈) | 코드 신규 | Task 3·4 |

나머지(모델, 스키마, 라우터, confirm 호출, 멱등성, 재고 복구)는 만들어져 있으니
**갈아엎지 말고 보강**하는 방향이다.

---

## 1. 코드 지도 — 먼저 읽어야 할 파일

읽는 순서대로 정렬했다. 각 파일이 "무슨 역할"이고 "지금 상태"가 어떤지.

| 순서 | 파일 | 역할 | 지금 상태 |
|---|---|---|---|
| 1 | [app/payment/models.py](../app/payment/models.py) | `Payment` 테이블, `PaymentStatus`/`PaymentMethod`/`PgProvider` enum | ✅ 완성. `PaymentStatus` 에 `WAITING_FOR_DEPOSIT` 없음(가상계좌 하면 추가) |
| 2 | [app/payment/adapters/ports.py](../app/payment/adapters/ports.py) | `PaymentGateway` **Protocol**(인터페이스) + `TossConfirmResult`/`TossPaymentResult` DTO | ✅ `confirm` + `get_payment` 있음. `cancel` 은 Task 3 |
| 3 | [app/payment/adapters/toss.py](../app/payment/adapters/toss.py) | 토스 REST API 실제 호출 어댑터 | ✅ `confirm`(보강은 Task 5) + `get_payment` 구현됨 |
| 4 | [app/payment/adapters/fake.py](../app/payment/adapters/fake.py) | 개발용 항상성공 어댑터 | ✅ `get_payment` 추가됨 |
| 5 | [app/payment/payment_service.py](../app/payment/payment_service.py) | 결제 비즈니스 로직 (init / confirm / webhook) | ✅ `handle_webhook` 이 조회 재확인 방식. `EXPIRED` 처리 추가됨 |
| 6 | [app/payment/payment_router.py](../app/payment/payment_router.py) | `/payments/init`, `/confirm`, `/webhooks/toss` | ✅ 서명 체크 제거, `handle_webhook` 위임만 |
| 7 | [app/payment/payment_schemas.py](../app/payment/payment_schemas.py) | 요청/응답 Pydantic DTO | ✅ 대체로 완성. `PaymentInitResponse` 에 `client_key` 없음 |
| 8 | [app/payment/payment_repository.py](../app/payment/payment_repository.py) | DB 접근 (락, 멱등 조회, 재고 복구) | ✅ 완성. 취소 반영용 메서드는 추가 필요 |
| 9 | [app/core/deps.py:244](../app/core/deps.py#L244) `get_payment_service` | `use_fake_pg` 로 Fake/Toss 게이트웨이 선택 | ✅ 완성 |
| 10 | [app/core/config.py:73](../app/core/config.py#L73) | `toss_secret_key`, `use_fake_pg` | ⚠️ `toss_client_key` 필드 없음 (`.env.example` 엔 있는데 코드엔 없음) |
| 11 | [app/order/order_service.py:200](../app/order/order_service.py#L200) `request_refund` / [:217](../app/order/order_service.py#L217) `cancel_order` | 사용자 주문 취소·환불 | ⚠️ *"PG 호출은 추후"* 주석. 상태만 바꿈 |
| 12 | [app/order/admin_order_service.py:87](../app/order/admin_order_service.py#L87) `cancel_order` | 관리자 주문 취소 | ⚠️ 동일. 상태만 바꿈 |

### 테스트 파일

| 파일 | 커버 |
|---|---|
| [tests/test_toss_adapter.py](../tests/test_toss_adapter.py) | `TossPaymentGateway.confirm` — `unittest.mock.patch` 로 `httpx.AsyncClient` 교체하는 패턴. **이 패턴을 그대로 재사용** |
| [tests/test_payment_service.py](../tests/test_payment_service.py) | `PaymentService` 단위 — `FakeRepo` + `FakeGateway` |
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

### Task 3 — `TossPaymentGateway.cancel()` 구현

**왜**: §0-C. 취소/환불 API 자체가 없다.

**뭘 바꾸나**:
1. `adapters/ports.py`:
   ```python
   async def cancel(
       self, *, payment_key: str, reason: str,
       cancel_amount: int | None = None,
   ) -> TossCancelResult: ...
   ```
   `TossCancelResult` DTO: `status`, `cancelled_amount`, `transaction_key`
2. `adapters/toss.py` `cancel` 구현:
   - `POST /v1/payments/{payment_key}/cancel`
   - 헤더에 `Idempotency-Key` (예: `f"cancel-{payment_key}-{cancel_amount or 'full'}"`)
   - body `{ cancelReason, cancelAmount? }`
   - 4xx → `PaymentFailedError(code+message)`, 네트워크 → `PaymentGatewayUnknownError`
3. `adapters/fake.py` `cancel` 추가 (항상 성공)
4. `confirm` 에도 `Idempotency-Key` 헤더 추가 (같이 하는 게 자연스러움)

**어떻게 검증** — `tests/test_toss_adapter.py`:
- `test_cancel_full_amount_calls_api_with_reason`
- `test_cancel_partial_amount_passes_cancel_amount`
- `test_cancel_4xx_raises_payment_failed_with_message`
- `test_cancel_timeout_raises_gateway_unknown_error`
- `test_confirm_sends_idempotency_key_header`

**완료 기준**: 정적 게이트 3종 그린.

---

### Task 4 — 주문 취소/환불에서 PG cancel 호출 연결

**왜**: Task 3 로 만든 `cancel` 을 실제 도메인 흐름에 연결.

**뭘 바꾸나**:
1. `payment_service.py` 에 `cancel_payment(order_id, reason, amount=None)` 추가:
   - 해당 주문의 `PAID` Payment 를 `FOR UPDATE` 락으로 조회
   - `self._gateway.cancel(payment_key=payment.pg_tid, reason=..., cancel_amount=amount)`
   - 성공 시 `payment.status = CANCELLED`(전액) / `PARTIAL_CANCELLED`(부분),
     `cancelled_at` 기록
   - 이미 `CANCELLED` 면 멱등 통과
2. `payment_repository.py`: `update_status_cancelled(payment, result)` 추가
3. `order_service.py`:
   - `cancel_order` / `request_refund` 에서 주문이 `PAID` 이상이면
     payment 서비스의 `cancel_payment` 호출 (PG 취소 성공해야 상태 전환)
   - `PENDING`(결제 전) 은 지금처럼 PG 호출 없이 상태만
4. `admin_order_service.py` `cancel_order` 도 동일
5. `deps.py`: order 서비스가 payment 서비스(또는 gateway)를 주입받도록 와이어링
   — 모듈 경계 주의(CLAUDE.md: cross-import 규칙). order → payment 서비스 호출은
   OK, order 가 payment repository 직접 호출은 금지

**어떻게 검증**:
- `tests/test_payment_service.py`: `test_cancel_payment_calls_gateway_and_marks_cancelled`,
  `test_cancel_payment_idempotent_when_already_cancelled`
- `tests/test_order_service.py`: `test_cancel_paid_order_triggers_pg_cancel`,
  `test_cancel_pending_order_skips_pg_cancel`
- `tests/test_admin_order_service.py`: 동일 취지
- 통합: `tests/integration/test_payment_service.py`

**완료 기준**: 정적 게이트 3종 그린. `docs/todo.md` §4 "12. PG 환불 실호출" 체크.

---

### Task 5 — confirm 응답 파싱 하드닝

**왜**: 실패 사유가 로그/DB 에 안 남아서 운영 시 "결제가 왜 실패했지"를 못 본다.
`method` 한글 문자열이 `PaymentMethod` enum 과 매핑 안 됨.

**뭘 바꾸나** — `adapters/toss.py` `confirm`:
- 4xx/5xx 일 때 `resp.json()` 의 `code`/`message` 를 꺼내
  `PaymentFailedError(f"{code}: {message}")` 로 던지기
- `payment_service.confirm_payment` 에서 이 에러 잡아 `payment.fail_reason` 저장 +
  `payment.status = FAILED` (지금은 그냥 예외 전파)
- 함수 안 `from datetime import datetime` → 모듈 상단으로 이동 (ruff)
- (선택) `method` 한글 → enum 매핑 헬퍼. 단 주문 시 이미 `PaymentMethod` 를
  받으므로 confirm 응답의 method 는 표시용으로만 쓸지 결정

**어떻게 검증**:
- `test_confirm_4xx_includes_toss_error_code_and_message`
- `test_confirm_payment_saves_fail_reason_on_rejection`

**완료 기준**: 정적 게이트 3종 그린.

---

### Task 6 — config / 환경변수 정리 + 실키 전환

**왜**: §0-A. 코드에 `toss_client_key` 필드가 없고, 실제 키가 안 들어가 있음.

**뭘 바꾸나** (CLAUDE.md: config 는 항상 3곳 동시 수정):
1. `app/core/config.py`: `toss_client_key: str | None = None` 추가
   (프론트가 위젯을 띄우려면 client key 가 필요. 백엔드가 `/payments/init`
   응답으로 내려줄지, 프론트 자체 env 로 둘지 결정 — 내려주는 쪽 권장)
2. `payment_schemas.py` `PaymentInitResponse` 에 `client_key: str` 추가
   + `payment_service.init_payment` 에서 `settings.toss_client_key` 채우기
3. `.env.example`: 이미 `TOSS_CLIENT_KEY` 있음 — 주석만 정리
4. 본인 `.env`: 토스 콘솔에서 **테스트 키** 발급받아 입력, `USE_FAKE_PG=false`
5. 토스 개발자센터에서:
   - 테스트 상점 → API 키(테스트) 발급
   - 웹훅 URL 등록: `https://{도메인}/api/v1/payments/webhooks/toss`
   - 등록할 이벤트: `PAYMENT_STATUS_CHANGED` (+ 가상계좌 하면 `DEPOSIT_CALLBACK`)
   - 결제창 허용 도메인 등록

**어떻게 검증**:
- `test_init_payment_returns_client_key`
- 로컬에서 `USE_FAKE_PG=false` + 테스트 키로 서버 띄우고
  토스 테스트 카드로 실제 결제창 → confirm → 웹훅 수신 end-to-end 1회

**완료 기준**: 테스트 결제 1건이 `payments` 테이블에 `PAID` 로 남고,
취소 테스트 1건이 `CANCELLED` 로 남음. `docs/todo.md` "[결제] Toss Payments 실키" 체크.

---

### Task 7 (선택) — 가상계좌(계좌이체) 입금대기 흐름

**언제**: MVP 에 계좌이체를 넣기로 했으면. 아니면 스킵하고 카드/간편결제만.

**뭘 바꾸나**:
- `PaymentStatus.WAITING_FOR_DEPOSIT` 추가 (+ Alembic — enum 이 `native_enum=False`
  라 VARCHAR 이므로 마이그레이션 불필요할 수 있음, 확인)
- `confirm` 후 `method` 가 가상계좌면 `PAID` 대신 `WAITING_FOR_DEPOSIT`
- `DEPOSIT_CALLBACK` 웹훅 처리 + `secret` 대조 검증
- 환불 시 `refundReceiveAccount`(은행/계좌/예금주) 입력 받는 스키마 추가

**완료 기준**: 정적 게이트 3종 그린 + 가상계좌 테스트 결제 왕복.

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

## 5. 시작 전 정해야 할 것 2가지

1. **계좌이체(가상계좌) 를 MVP 에 넣나?**
   - 넣는다 → Task 7 포함, 일정 +1~2일
   - 뺀다 → 카드 + 간편결제(카카오/네이버/토스페이)만. `PaymentMethod` 에서
     `BANK` 를 주문서에서 숨김
2. **부분취소를 지금 구현하나?**
   - 지금 → Task 4 에서 `cancel_amount` 경로 + `PARTIAL_CANCELLED` 재고 정책 필요
   - 나중 → 전액취소만. 부분취소 웹훅은 수신·기록만 하고 재고는 안 건드림 (현재 TODO 주석 상태 유지)

> 권장: **둘 다 "나중"** 으로 두고 카드/간편결제 + 전액취소만으로 먼저 오픈.
> 그러면 Task 1~6 + 8 만. 대략 6일치.

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

# 실키 로컬 테스트
# .env 에 TOSS_CLIENT_KEY/TOSS_SECRET_KEY(테스트키) + USE_FAKE_PG=false
.venv/bin/uvicorn app.main:app --reload

# MCP 문서 검색 서버 확인
claude mcp list
```
