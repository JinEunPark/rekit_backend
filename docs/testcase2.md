# 결제 실연동 전 동시성/멱등성 2차 점검 — 작업 목록

> **배경**: `docs/testcase.md`(1차) 작업 완료 후, 실제 PG 연동을 앞두고 코드를
> 다시 훑은 결과 **락이 아예 빠진 경로 3곳**과 **웹훅 멱등성 가드가 정상
> 이벤트까지 막아버리는 로직 버그 1곳**을 추가로 발견했다. `testcase.md`가
> 다루지 않은 신규 항목만 다룬다 — 그 문서에서 이미 락을 건 경로(관리자 취소,
> confirm_payment, init_payment 등)는 재론하지 않는다.
>
> **사용법**: `testcase.md`와 동일 — Red(실패 테스트) → Green(구현) →
> Refactor 순으로 진행. 체크박스를 갱신하며 세션 간 이어간다. 코드 스니펫은
> 실제 파일을 읽고 작성했지만 라인 번호는 앞선 작업으로 어긋날 수 있음 —
> **함수/메서드 이름을 신뢰할 것.**
>
> **작성일**: 2026-07-10

---

## 발견 항목 ↔ Task 매핑표

| 발견 항목 | 내용 | 대응 Task | 심각도 |
|---|---|---|---|
| F-1 | 사용자 주문취소(`OrderService.cancel_order`) — Order 조회에 락 없음 | Task 1 | ★★★ |
| F-2 | PENDING 타임아웃 만료(`_expire_if_abandoned`) — 락 없음 | Task 2 | ★★☆ |
| F-3 | `handle_webhook` 전체 — Payment/Order 조회에 락 없음 | Task 3 | ★★★ |
| F-4 | 웹훅 멱등 가드가 PAID 이후 정상 CANCELED(환불) 이벤트까지 차단 | Task 4 | ★★★ |
| F-5 | Task 5-2(`testcase.md`) 동시 confirm 테스트가 계획만 있고 미구현 | Task 5-1 | ★★☆ |
| F-6 | `init_payment` 락의 실제 원자성(동시 호출 시 READY 1개만) 미검증 | Task 5-2 | ★☆☆ |
| F-7 | 웹훅 fallback 경로와 confirm 동시 실행 시 안전성 미검증 | Task 5-3 | ★☆☆ |

**권장 순서**: `Task 1 → Task 3 → Task 4 → Task 2`, 그 다음 `Task 5` (검증만, 신규 로직 없음).

---

## Task 1 — `OrderService.cancel_order` 동시 취소 방지 (Order 락 추가)

**현재 코드** (`app/order/order_service.py:212-228`):
```python
async def cancel_order(self, user_id: int, order_number: str) -> OrderResponse:
    order = await self._get_order_for_user(user_id, order_number)   # 락 없는 SELECT
    if order.status not in _CANCELLABLE_STATUSES:
        raise OrderCancelForbiddenError()
    for item in order.items:
        await self._repo.increment_stock(item.product_id, item.quantity)
    order.status = OrderStatus.CANCELLED
    order.cancelled_at = datetime.now(UTC)
    return _to_order_response(order)
```

`_get_order_for_user`(255줄대)는 `OrderRepository.get_by_order_number`(`order_repository.py:41-49`)를
쓰는데 `.with_for_update()`가 없다. 관리자용 취소(`AdminOrderService.cancel_order`,
`testcase.md` Task 1-3)는 이미 락을 걸었는데 **사용자용은 빠져 있다** — 더블클릭이나
클라이언트 자동 재시도로 취소 요청이 근접 시간에 두 번 들어오면 둘 다
`status in _CANCELLABLE_STATUSES` 체크를 통과해 `increment_stock`이 중복 호출된다
→ 실제 재고보다 많이 복구되는 오버카운트 버그.

### 1-1. `OrderRepository`에 락 버전 조회 추가

- [x] `get_by_order_number_with_lock(order_number: str) -> Order | None` 추가
      (`get_by_order_number`와 동일하되 `.with_for_update()` + `selectinload(Order.items)` 유지).
      → `app/order/order_repository.py` `get_by_order_number_with_lock`
- [x] `cancel_order`가 `_get_order_for_user` 대신 이 락 버전을 쓰도록 분리
      (`_get_order_for_user`는 조회 전용 경로(`get_order`, `request_refund` 등)에
      계속 락 없이 쓰이므로 공유 헬퍼를 억지로 통일하지 않는다 — 취소만 락 필요).
      → `app/order/order_service.py` `cancel_order`

**TDD**:

`tests/test_order_service.py` (단위, fake repo spy):
1. `test_cancel_order_uses_locked_read`
   - fake repo에 `get_by_order_number_with_lock` 호출 카운터 추가
   - `cancel_order` 호출 시 락 버전이 정확히 1회 호출되는지 (락 없는 버전은 호출 안 됨)

`tests/integration/test_order_repository.py` 또는 신규
`tests/integration/test_order_service.py` (실제 DB 락 타이밍 필요):
2. `test_cancel_order_concurrent_double_click_only_restores_stock_once`
   - Given: 재고 N인 상품 1개로 만든 PENDING 주문(quantity=2, 생성 시 이미 차감된 상태 가정)
   - When: `asyncio.gather`로 동일 `order_number`에 대해 `cancel_order`를 거의 동시에 두 번 호출
   - Then: 재고가 정확히 1회분만 복구됨, 두 번째 호출은 `OrderCancelForbiddenError`
     (이미 CANCELLED)로 실패 — 두 응답 중 정확히 하나만 성공해야 함
   - 참고: 동일 기법은 `testcase.md` Task 5-2 / Task 7 통합 테스트에서 이미 사용한
     "짧은 타임아웃으로 블록 여부 간접 확인" 패턴 재사용

---

## Task 2 — `_expire_if_abandoned` 동시 만료 방지

**현재 코드** (`app/order/order_service.py:241-253`):
```python
async def _expire_if_abandoned(self, order: Order) -> None:
    if order.status != OrderStatus.PENDING:
        return
    if datetime.now(UTC) - order.created_at < _PAYMENT_TIMEOUT:
        return
    for item in order.items:
        await self._repo.increment_stock(item.product_id, item.quantity)
    order.status = OrderStatus.CANCELLED
    order.cancelled_at = datetime.now(UTC)
```

`get_order`가 이 헬퍼를 호출하는데, 여기 전달되는 `order`도 락 없는 조회 결과다.
프론트가 결제 대기 화면에서 주기적으로 `GET /orders/{id}`를 폴링하거나 탭을 두 개
열어두면 30분 경과 시점에 두 요청이 동시에 만료 처리를 시도해 재고가 이중
복구될 수 있다.

**설계 결정 필요** (구현 전에 정할 것):
- Task 1처럼 무조건 락을 걸면 `get_order`(단순 조회 API)의 매 호출마다
  불필요하게 행을 잠그게 되어 조회 성능이 나빠진다.
- 권장: **2단계 확인** — 1차로 지금처럼 락 없이 만료 후보인지 판단하고,
  후보(PENDING & 타임아웃 초과)일 때만 `get_by_order_number_with_lock`
  (Task 1-1에서 추가한 것 재사용)으로 재조회해 **락을 잡은 뒤 상태를 한 번
  더 확인**(더블 체크 — 그 사이 다른 트랜잭션이 이미 취소했을 수 있음)하고
  나서 복구를 진행한다.

- [x] 위 2단계 패턴으로 `_expire_if_abandoned` 재구현.
      → `app/order/order_service.py` `_expire_if_abandoned` (L244-L262)
      → `app/order/order_repository.py` `get_by_order_number_with_lock` — `populate_existing=True` 추가 (SQLAlchemy identity map 캐시 우회 필수)
- [x] 락 재조회 후 이미 `CANCELLED`면 조용히 스킵 (중복 복구 방지).
      → `app/order/order_service.py` L257: `if locked_order.status != PENDING: return`

**TDD** (`tests/test_order_service.py`):
1. `test_get_order_expire_double_checks_status_after_lock`
   - Given: 락 재조회 시 이미 다른 트랜잭션이 CANCELLED로 바꿔놓은 상황을
     fake repo로 시뮬레이션(락 조회 메서드가 CANCELLED 주문을 반환하도록)
   - Then: `increment_stock` 호출 없음 (이중 복구 방지 확인)

`tests/integration/`(신규):
2. `test_get_order_concurrent_abandonment_expires_stock_once`
   - Given: 30분 경과한 PENDING 주문
   - When: `asyncio.gather`로 `get_order`를 동시에 두 번 호출
   - Then: 재고 복구가 정확히 1회만 반영됨

---

## Task 3 — `PaymentService.handle_webhook` 락 보강

**현재 코드** (`app/payment/payment_service.py:174-229`) — 요약:
```python
payment = await self._repo.get_by_pg_tid(pg_tid)                      # 락 없음
...
payment = await self._repo.get_ready_payment_by_order_number(...)     # 락 없음 (fallback)
...
async def _restore_order_stock_and_cancel(self, order_id: int) -> None:
    order = await self._repo.get_order_by_id(order_id)                # 락 없음
    if order is None or order.status == OrderStatus.CANCELLED:
        return
    for item in order.items:
        await self._repo.increment_stock(item.product_id, item.quantity)
    order.status = OrderStatus.CANCELLED
    ...
```

`confirm_payment`는 `testcase.md` Task 5-2에서 `get_by_order_id_with_lock`을 추가했지만
**웹훅 경로는 락 보강이 통째로 빠졌다.** 토스는 200 응답을 못 받으면 웹훅을
재전송하는 정책이라(`payment_router.py` 주석에도 명시) 같은 이벤트가 짧은 간격으로
중복/동시 도착하는 건 실제 운영에서 드물지 않다. ABORTED/CANCELED 웹훅이 동시에
두 번 도착하면 `order.status == CANCELLED` 가드를 둘 다 (커밋 전) 통과해 재고가
이중 복구될 수 있다.

### 3-1. 락 버전 조회 메서드 추가

- [x] `PaymentRepository.get_by_pg_tid_with_lock(pg_tid: str) -> Payment | None`
      (`.with_for_update()` 추가)
      → `app/payment/payment_repository.py` `get_by_pg_tid_with_lock`
- [x] `PaymentRepository.get_ready_payment_by_order_number_with_lock(order_number: str) -> Payment | None`
      (내부 `Order` 조회는 그대로 두고, `Payment` SELECT에만 `.with_for_update()`)
      → `app/payment/payment_repository.py` `get_ready_payment_by_order_number_with_lock`
- [x] `PaymentRepository.get_order_by_id_with_lock(order_id: int) -> Order | None`
      (`get_order_by_id`와 동일 + `.with_for_update()`, `selectinload(Order.items)` 유지)
      → `app/payment/payment_repository.py` `get_order_by_id_with_lock`
- [x] `handle_webhook`/`_restore_order_stock_and_cancel`이 위 락 버전을 쓰도록 교체.
      → `app/payment/payment_service.py` `handle_webhook`, `_restore_order_stock_and_cancel`

**TDD**:

`tests/test_payment_service.py` (단위, spy):
1. `test_handle_webhook_uses_locked_payment_read` — `get_by_pg_tid_with_lock` 호출 확인

`tests/integration/`(신규, `tests/integration/test_payment_service.py`):
2. `test_webhook_aborted_concurrent_delivery_restores_stock_once`
   - Given: READY 결제, PENDING 주문(items 포함)
   - When: `asyncio.gather`로 동일 `payload`(ABORTED)를 `handle_webhook`에 거의 동시에 두 번 전달
   - Then: 재고가 정확히 1회분만 복구, `order.status == CANCELLED`는 한 번만 전이
   - 참고: flaky 위험 있음 — `testcase.md` Task 5-2 통합 테스트와 동일하게 실패 시
     재실행 후에도 깨지면 락 구현을 재검토

---

## Task 4 — PAID 이후 정상 CANCELED(환불) 웹훅이 무시되는 로직 버그 수정

**현재 코드** (`app/payment/payment_service.py:198-200`):
```python
# 멱등성: 이미 PAID 이면 중복 처리 없음
if payment.status == PaymentStatus.PAID:
    return
```

이 가드가 `pg_status` 분기보다 **먼저** 실행돼서, 결제가 이미 PAID인 상태에서
도착하는 **모든** 후속 웹훅을 무조건 무시한다. 문제는 "PAID 후 진짜로 취소/환불"이
정상적인 운영 시나리오라는 것 — 예를 들어 고객센터 환불 처리나 부분 취소가
토스 대시보드에서 발생하면 토스가 `CANCELED`/`PARTIAL_CANCELED` 웹훅을 보내는데,
그 시점엔 `payment.status`가 이미 `PAID`라서 **이 정상 이벤트가 조용히 드롭된다.**
결과: PG 쪽은 환불됐는데 우리 DB는 영원히 `PAID` 상태로 남고 재고도 복구되지 않는다.

`test_webhook_idempotent_already_paid`(`tests/test_payment_service.py:428`)는
"DONE 중복 수신"만 검증하고 이 케이스는 다루지 않는다 — 테스트만 있어서
보호되고 있다고 착각하기 쉬운 지점.

### 4-0. 상태 전이 정책 결정 (구현 전 필수)

- [x] **결정 필요**: `Payment.status`가 `PAID → CANCELLED`로 전이하는 걸 허용할지
      (허용해야 함 — 이게 이번 수정의 핵심). `PAID → FAILED`(ABORTED 웹훅이 PAID
      이후 도착하는 경우)는 PG 쪽에서 나올 수 없는 조합이므로 로그만 남기고
      무시하는 게 안전한지 확인.
      → 정책 결정: PAID→CANCELLED 허용, PAID+ABORTED는 logger.warning 후 무시

### 4-1. 가드를 `pg_status`별로 세분화

**목표 코드** (개략):
```python
if payment.status == PaymentStatus.PAID:
    if pg_status == _TOSS_DONE:
        return  # 중복 확인 웹훅 — 기존 의도 그대로 무시
    if pg_status in (_TOSS_CANCELED, _TOSS_PARTIAL_CANCELED):
        pass  # PAID 이후 정상 취소/환불 — 아래 공통 로직으로 흘려보냄
    else:
        # ABORTED가 PAID 이후 도착 — PG 쪽에서 나올 수 없는 조합, 방어적으로 무시
        logger.warning("PAID 결제에 ABORTED 웹훅 도착 — 무시: pg_tid=%s", pg_tid)
        return
```

- [x] 위 로직 적용. `elif` 체인(`_TOSS_DONE` / `_TOSS_CANCELED,_TOSS_PARTIAL_CANCELED` /
      `_TOSS_ABORTED`) 자체는 그대로 재사용 가능 — 맨 위 조기 return만 세분화.
      → `app/payment/payment_service.py` `handle_webhook` (pg_status 먼저 읽고 PAID 가드 세분화)
- [x] `import logging` 및 모듈 레벨 `logger` 추가(현재 파일에 없음).
      → `app/payment/payment_service.py` L5, L26

**TDD** (`tests/test_payment_service.py`):
1. `test_webhook_canceled_after_paid_restores_stock_and_cancels_order`
   - Given: `Payment(status=PAID, pg_tid="pk_1")`, `Order(status=PAID)`, items 포함
   - When: `handle_webhook` with `data.status == "CANCELED"`
   - Then: `payment.status == CANCELLED`, `order.status == CANCELLED`,
     `increment_stock` 호출됨 (Task 1-4 로직과 동일하게 동작하는지 확인)
2. `test_webhook_partial_canceled_after_paid_does_not_restore_stock`
   - 위와 동일하되 `PARTIAL_CANCELED` — 재고 복구는 안 됨(기존 정책 유지)
3. `test_webhook_aborted_after_paid_is_ignored`
   - Given: `Payment(status=PAID)`
   - When: `status == "ABORTED"` 웹훅 도착 (비정상 케이스)
   - Then: `payment.status`는 `PAID` 그대로, 예외 없음, 재고 변화 없음
4. `test_webhook_done_after_paid_is_still_idempotent_noop`
   - 기존 `test_webhook_idempotent_already_paid` 회귀 — 이번 리팩터 후에도 깨지지
     않는지 (DONE 중복은 여전히 무시)

---

## Task 5 — 기존 락 로직 동시성 검증 보강 (신규 프로덕션 코드 없음, 테스트만)

### 5-1. `testcase.md` Task 5-2 계획됐던 동시 confirm 테스트 실제 작성

- [x] `tests/integration/test_payment_service.py`(Task 3-1 통합 테스트 파일과 통합 또는
      신규): `test_confirm_payment_concurrent_calls_only_one_gateway_call`
      - `asyncio.gather`로 동일 주문에 `confirm_payment`를 거의 동시에 두 번 호출,
        `gateway.confirm` 총 호출 수가 1인지 확인 (`get_by_order_id_with_lock`이
        실제로 두 번째 호출을 블로킹하는지 검증)
      → `tests/integration/test_payment_service.py` `test_confirm_payment_concurrent_calls_only_one_gateway_call`

### 5-2. `init_payment` 락의 실제 원자성 검증

- [x] `tests/integration/`(신규 또는 기존 파일):
      `test_init_payment_concurrent_calls_creates_only_one_ready_payment`
      - `asyncio.gather`로 동일 주문에 `init_payment`를 거의 동시에 두 번 호출,
        DB에 READY `Payment`가 정확히 1개만 생성됐는지 (`get_order_by_number_with_lock`
        실제 블로킹 검증)
      → `tests/integration/test_payment_service.py` `test_init_payment_concurrent_calls_creates_only_one_ready_payment`

### 5-3. 웹훅 fallback과 confirm 동시 실행 안전성

- [x] `test_webhook_fallback_and_confirm_race_does_not_double_process`
      - Given: confirm이 아직 실행 안 된 READY 결제(`pg_tid=None`)
      - When: `asyncio.gather`로 `confirm_payment`와 `handle_webhook`(fallback 경로)을
        거의 동시에 실행
      - Then: 최종적으로 `Payment`가 정확히 한 번만 PAID로 전이되고, 이메일/PG
        호출 등 부수효과가 중복되지 않는지 (게이트웨이 호출 횟수 등으로 간접 확인)
      → `tests/integration/test_payment_service.py` `test_webhook_fallback_and_confirm_race_does_not_double_process`

---

## 세션 재개 체크리스트

1. 이 파일에서 체크 안 된 첫 Task부터 확인 (권장 순서: Task 1 → 3 → 4 → 2 → 5).
2. `git status`/`git log`로 이미 반영된 코드가 있는지 실제 코드 기준 재확인 —
   이 문서의 체크박스보다 코드가 진실.
3. 각 Task 안의 "현재 코드" 스니펫이 실제 파일과 다르면(이전 Task로 이미
   변경됐을 수 있음) 실제 파일을 다시 읽고 진행.
4. `CLAUDE.md`의 게이트(`pytest` / `ruff check app tests` / `mypy app`)를 전부
   통과한 상태에서만 다음 Task로 이동.
5. **커밋/푸시는 사용자가 명시적으로 요청할 때만** — 자동 루프로 실행 중이어도
   이 규칙은 동일하게 적용된다. 작업 완료 후 diff만 남기고 커밋하지 않는다.
