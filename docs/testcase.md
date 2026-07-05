# 결제 연동 전 동시성/정합성 버그 수정 — 작업 목록 (상세판)

> **배경**: 결제(PG) 연동 전 엣지케이스를 점검한 결과, 재고 동시성 자체는
> `SELECT ... FOR UPDATE` 락으로 이미 안전하지만, **취소/실패 시 재고 미복구**,
> **웹훅↔주문 상태 불일치**, **confirm 멱등성 부재** 등 더 심각한 문제를 발견했다.
> 이 문서는 그 문제들을 고치기 위한 작업을 TDD 단위로 세분화한 목록이다.
>
> **사용법**: 각 작업은 Red(실패 테스트 작성) → Green(구현) → Refactor 순으로
> 진행한다. 체크박스를 진행하면서 갱신하고, 세션이 끝나면 이 파일 상태만 보고
> 다음 세션에서 이어갈 수 있어야 한다. 완료된 작업은 `[x]`로 표시하고 실제
> 구현 파일/라인을 주석으로 남긴다. 코드 스니펫은 전부 실제 파일을 읽고
> 작성했지만, 라인 번호는 앞선 작업으로 파일이 바뀌면 어긋날 수 있다 —
> **라인 번호보다 함수/메서드 이름을 신뢰할 것.**
>
> **작성일**: 2026-07-06 / **상세화**: 2026-07-06 (2차)

---

## 발견 항목 ↔ Task 매핑표 (추적용)

| 발견 항목 | 내용 | 대응 Task |
|---|---|---|
| A-1 | 주문 취소해도 재고 미복구 (사용자) | Task 1-2 |
| A-1 | 주문 취소해도 재고 미복구 (관리자) | Task 1-3 |
| A-2 | PENDING 방치 주문 타임아웃 없음 | Task 2 |
| B-4 | `init_payment` 멱등성 부재 | Task 4 |
| B-5 | `confirm_payment` READY 건 임의 선택 | Task 5-1 |
| B-6 | 동시 confirm → PG 이중 호출 | Task 5-2 |
| B-7 | `confirm_payment`가 `order.status` PENDING 미검증 | Task 5-3 |
| B-8 | 웹훅 PAID 처리 시 `order.status` 미갱신 | Task 3-1 |
| B-9 | 웹훅이 confirm보다 먼저 오면 무시됨 (pg_tid 없음) | Task 3-2 |
| B-10 | PG confirm 네트워크 에러 시 상태 불명 | Task 6 |
| C-11 | 결제 거절(ABORTED) 웹훅 — 재고/주문 미처리 | Task 1-4 |
| C-12 | 결제 취소(CANCELED) 웹훅 — 재고/주문 미처리 | Task 1-4 |
| D-13 | 관리자 상품수정 lost update 가능성 | Task 7 |
| E-15 | PG에 클라이언트 amount 그대로 전달 | Task 8 |
| E-14, E-16 | 금액 검증/웹훅 서명 검증 — **이미 안전, 조치 불필요** | 없음 (회귀 테스트만 유지) |

---

## 우선순위 요약

| # | 작업 | 심각도 | 선행 조건 |
|---|---|---|---|
| 1 | 재고 복구 (취소/실패/타임아웃) | ★★★ | 없음 — 지금 바로 시작 가능 |
| 2 | PENDING 주문 타임아웃 자동취소 | ★★☆ | Task 1 (복구 로직 재사용) |
| 3 | 웹훅 ↔ 주문 상태 동기화 | ★★★ | Task 5 (READY 매칭 정리 후가 더 안전) |
| 4 | init_payment 멱등성 | ★★☆ | 없음 |
| 5 | confirm_payment 매칭/락/상태검증 | ★★☆ | Task 4 |
| 6 | confirm 네트워크 에러 reconciliation | ★★☆ | Task 3 (웹훅이 최종 진실을 알려줘야 함) |
| 7 | 관리자 상품수정 lost update 방지 | ★☆☆ | 없음 (독립적, 후순위) |
| 8 | 결제금액 서버값 사용으로 통일 | ★☆☆ | 없음 (독립적, 아무때나) |

**권장 순서**: `Task 1 → Task 4 → Task 5 → Task 3 → Task 6`, 그 사이 여유 있을 때 `Task 2 / 7 / 8` 끼워넣기.

---

## 사전 지식 — 지금 코드가 이미 막고 있는 것 (재확인)

`app/order/order_service.py::create_order` (104-155):

```python
product_ids = [i.product_id for i in req.items]
product_map = await self._repo.get_products_with_lock(product_ids)   # SELECT ... FOR UPDATE
for item_req in req.items:
    product = product_map.get(item_req.product_id)
    if product is None or product.status != ProductStatus.ACTIVE:
        raise ProductUnavailableError()
    if product.stock < item_req.quantity:
        raise OutOfStockError()
...
await self._repo.save(order)                     # flush, PK 확보
await self._repo.update_order_number(order, ...)
for item_req in req.items:
    await self._repo.decrement_stock(item_req.product_id, item_req.quantity)  # 원자적 UPDATE
```

이 전체가 라우터 계층의 `db_session` 컨텍스트(`app/core/deps.py`) 안에서 **하나의 트랜잭션**으로 처리된다.
`get_products_with_lock`이 `FOR UPDATE`로 상품 행을 잠그기 때문에, 동시에 같은 상품에 대해
`create_order`를 호출하는 두 번째 요청은 첫 번째 트랜잭션이 커밋(또는 롤백)할 때까지
그 `SELECT ... FOR UPDATE`에서 **대기**한다. 첫 번째가 커밋되면 두 번째는 갱신된 `stock`을
다시 읽어 부족하면 `OutOfStockError`로 막힌다 — 이 경로는 검증됨, **수정 불필요**.

**핵심 전제**: 재고 차감은 결제 시점이 아니라 **주문 생성 시점**에 끝난다. 이 전제 때문에
"차감된 재고를 원래대로 돌리는 경로가 하나도 없다"는 사실이 훨�다 더 심각해진다 — 이게 Task 1이다.

---

## Task 1 — 재고 복구 (취소/실패/타임아웃)

### 1-0. 공용 복구 헬퍼 위치 결정 (선행 작업)

재고 복구가 필요한 지점이 최소 4곳(사용자 취소/관리자 취소/웹훅 실패/웹훅 취소)이므로,
각자 따로 구현하면 Reuse 위반이 즉시 발생한다. 먼저 공용 함수를 어디에 둘지 결정한다.

- [x] **결정**: `app/order/order_repository.py`에 `increment_stock` 원자적 SQL만 추가하고,
      "order.items를 순회하며 각 상품에 increment_stock을 호출"하는 **오케스트레이션**은
      각 서비스(`OrderService`, `AdminOrderService`, `PaymentService`)가 개별적으로
      호출하게 둘지, 아니면 `app/order/` 밑에 모듈 레벨 순수 함수
      `restore_stock_for_order(repo, order: Order) -> None`을 만들어 세 서비스가
      공유할지 결정. → **권장: 후자**. 단, `PaymentService`는 `app/order/`를 직접
      import하면 안 되므로(모듈 의존 규칙 — CLAUDE.md "router→service→repository→models
      일방향, cross-module 은 FK/relationship 만") `PaymentService`가 재고를 복구하려면
      `OrderRepository`(또는 그 메서드)를 주입받아야 함. 지금 `PaymentService`는
      `PaymentRepository`만 갖고 있으므로, **`PaymentRepository`에도 재고 복구용
      메서드를 추가**하거나 `PaymentService` 생성자에 `OrderRepository`를 추가 주입할지
      결정 필요. → **권장: `PaymentRepository`에 `increment_stock` 메서드를 그대로
      복제(2줄짜리 원자적 UPDATE라 중복 비용이 낮음)하고, "order.items 순회" 오케스트레이션
      로직만 각 서비스에 남긴다.** (모듈 간 결합을 늘리는 것보다 이 정도 중복이 더 싸다는
      판단 — 나중에 실제로 3벌째 복붙되는 게 보이면 그때 공용화해도 늦지 않음. 지금은
      섣부른 추상화보다 명시적 중복 허용.)

### 1-1. `OrderRepository.increment_stock` 추가

**현재 코드** (`app/order/order_repository.py:130-137`):
```python
async def decrement_stock(self, product_id: int, quantity: int) -> None:
    """재고를 quantity 만큼 감산 (SQL UPDATE — Python 루프 없이 원자적 처리)."""
    stmt = (
        update(Product)
        .where(Product.id == product_id)
        .values(stock=Product.stock - quantity)
    )
    await self._session.execute(stmt)
```

**추가할 코드** (바로 아래에):
```python
async def increment_stock(self, product_id: int, quantity: int) -> None:
    """재고를 quantity 만큼 가산 (주문 취소/실패 시 복구용). 원자적 UPDATE."""
    stmt = (
        update(Product)
        .where(Product.id == product_id)
        .values(stock=Product.stock + quantity)
    )
    await self._session.execute(stmt)
```

- [x] `app/order/order_repository.py`에 위 메서드 추가. (커밋 `b88c9fd`)
- [x] `app/payment/payment_repository.py`에도 동일한 메서드 추가 (1-0의 결정에 따름).
      단, `PaymentRepository`는 `Product`를 import하지 않고 있으므로
      `from app.catalog.models import Product`와 `from sqlalchemy import update` 추가 필요.
      (커밋 `b88c9fd`)

**TDD** (`tests/integration/test_order_repository.py`, 신규 파일 —
이 repo는 여태 단위 테스트가 없었다. `SELECT ... FOR UPDATE`/원자적 SQL 정확성은
fake repo로 검증할 수 없으므로 `tests/integration/conftest.py`의 `db_session` fixture 사용):

1. `test_increment_stock_adds_quantity`
   - Given: `Product(stock=5)`를 실제 DB에 저장(seed 또는 테스트 내 생성)
   - When: `await repo.increment_stock(product.id, 2)` 후 `session.refresh(product)` (또는 재조회)
   - Then: `product.stock == 7`
2. `test_increment_stock_and_decrement_stock_are_symmetric`
   - Given: `stock=10`
   - When: `decrement_stock(id, 3)` → `increment_stock(id, 3)`
   - Then: `stock == 10` (원위치 확인 — 두 연산이 서로 역함수임을 고정하는 회귀 테스트)

**Task 1-1 완료** (커밋 `b88c9fd`) — `tests/integration/test_order_repository.py` 2개
테스트 모두 통과. `PaymentRepository`는 문서 계획대로 자체 `increment_stock`을
따로 구현(중복 허용, 1-0 결정 참고).

---

### 1-2. `OrderService.cancel_order` — 취소 시 재고 복구

**현재 코드** (`app/order/order_service.py:208-221`):
```python
async def cancel_order(self, user_id: int, order_number: str) -> OrderResponse:
    order = await self._get_order_for_user(user_id, order_number)
    if order.status not in _CANCELLABLE_STATUSES:
        raise OrderCancelForbiddenError()
    order.status = OrderStatus.CANCELLED
    order.cancelled_at = datetime.now(UTC)
    return _to_order_response(order)
```

**문제**: `order.items`에 대한 재고 복구 호출이 전혀 없다. `_CANCELLABLE_STATUSES = {PENDING, PAID, PREPARING}`이므로
결제 전(PENDING)뿐 아니라 **결제 후(PAID/PREPARING)** 취소도 이 경로를 타는데, 결제 후 취소는
PG 환불(refund)도 같이 일어나야 정상이지만 그건 이 문서의 범위 밖(`request_refund`가 "MVP:
상태만 전환"이라 명시돼 있고 그 결정은 유지) — **이 Task에서는 재고 복구만 추가한다.**

**목표 코드**:
```python
async def cancel_order(self, user_id: int, order_number: str) -> OrderResponse:
    order = await self._get_order_for_user(user_id, order_number)
    if order.status not in _CANCELLABLE_STATUSES:
        raise OrderCancelForbiddenError()

    for item in order.items:
        await self._repo.increment_stock(item.product_id, item.quantity)

    order.status = OrderStatus.CANCELLED
    order.cancelled_at = datetime.now(UTC)
    return _to_order_response(order)
```

- [ ] 위 변경 적용. **순서 주의**: 재고 복구를 먼저 하고 상태 전환을 나중에 하든 순서
      자체는 트랜잭션 내에서 원자적으로 같이 커밋되므로 상관없음 — 다만 재고 복구 도중
      예외가 나면 상태 전환도 같이 롤백돼야 하므로, **같은 트랜잭션 안에서 처리되는지
      반드시 확인** (지금처럼 `db_session` 컨텍스트가 감싸는 형태면 자동으로 보장됨).

**TDD** (`tests/test_order_service.py`, `TestCancelOrder` 클래스 — 없으면 신규):

fake repo(`_FakeOrderRepo` 등 기존 파일에 있는 fake를 확인/재사용)에
`increment_stock` 메서드가 없다면 추가 필요 — 아래처럼 호출 기록(spy)까지 하도록:
```python
async def increment_stock(self, product_id: int, quantity: int) -> None:
    self.increment_calls.append((product_id, quantity))  # spy 용
    for p in self._products:
        if p.id == product_id:
            p.stock += quantity
```

1. `test_cancel_order_restores_stock_for_single_item`
   - Given: 재고 3인 상품 1개, 수량 2로 주문(PENDING) → 생성 후 재고는 이미 1
     (주문 생성 로직이 차감한 상태라고 가정하고 fixture를 그렇게 구성, 또는
     주문을 직접 만들어 order.items에 quantity=2 세팅하고 product.stock=1로 시작)
   - When: `cancel_order(user_id, order.order_number)`
   - Then: `product.stock == 3` (1 + 2), `increment_calls == [(product.id, 2)]`
2. `test_cancel_order_restores_stock_for_multiple_items`
   - Given: 라인 2개(상품 A 수량 1, 상품 B 수량 3)인 주문
   - When: 취소
   - Then: A는 +1, B는 +3 — 각각 정확한 상품 ID/수량으로 개별 호출됐는지
     (`increment_calls`에 두 튜플이 정확히 들어있는지)
3. `test_cancel_already_cancelled_order_raises_and_does_not_restore_stock`
   - Given: 이미 `status=CANCELLED`인 주문
   - When: 다시 `cancel_order` 호출
   - Then: `OrderCancelForbiddenError` 발생 **and** `increment_calls`가 비어있음
     (기존 상태 체크가 이미 막고 있는지 확인하는 회귀 테스트 — 중복 복구 방지 확인)
4. `test_cancel_paid_order_also_restores_stock`
   - Given: `status=PAID`인 주문 (결제 후 취소 케이스)
   - When: 취소
   - Then: 재고 복구는 여전히 일어남 (PG 환불은 별도 처리라는 걸 주석으로 명시)

---

### 1-3. `AdminOrderService.cancel_order` — 관리자 취소 시 재고 복구

**현재 코드** (`app/order/admin_order_service.py:87-97`):
```python
async def cancel_order(
    self, order_number: str, body: AdminOrderCancelRequest
) -> AdminOrderDetail:
    order = await self._repo.get_order_for_update(order_number)
    if order is None:
        raise OrderNotFoundError()
    if order.status not in _CANCELLABLE:
        raise OrderCancelForbiddenError()
    order.status = OrderStatus.CANCELLED
    order.cancelled_at = datetime.now(UTC)
    return await self.get_order(order_number)
```

**참고(부수 발견, 이 Task와 별개로 기록만)**: `get_order_for_update`라는 이름인데
실제로 `.with_for_update()`를 쓰지 않는다 (`admin_order_repository.py:81-86` 확인).
이름이 동작을 속이고 있음 — 이 Task에서 재고 복구를 추가하면서 **실제로 락도 걸도록
같이 고치는 게 좋음** (재고 복구는 Product 행을 건드리므로, Order 락과 별개로
Product 락도 필요 — 아래 참고).

**목표 코드**:
```python
async def cancel_order(
    self, order_number: str, body: AdminOrderCancelRequest
) -> AdminOrderDetail:
    order = await self._repo.get_order_for_update(order_number)  # 실제로 FOR UPDATE 걸도록 같이 수정
    if order is None:
        raise OrderNotFoundError()
    if order.status not in _CANCELLABLE:
        raise OrderCancelForbiddenError()

    for item in order.items:
        await self._repo.increment_stock(item.product_id, item.quantity)

    order.status = OrderStatus.CANCELLED
    order.cancelled_at = datetime.now(UTC)
    return await self.get_order(order_number)
```

- [ ] `app/order/admin_order_repository.py::get_order_for_update`(81-86)에
      `.with_for_update()` 추가 (지금 안 걸려있는 버그성 네이밍 불일치 수정).
      **주의**: `.options(selectinload(...))`와 `.with_for_update()`를 같이 쓸 때
      SQLAlchemy/Postgres 조합에 따라 `FOR UPDATE`가 JOIN된 테이블까지 잠그려다
      에러가 나는 경우가 있음(`FOR UPDATE cannot be applied to the nullable side
      of an outer join` 류) — `get_by_order_number`(68-78)처럼 여러 relationship을
      selectinload 하는 구조라면, **락은 `Order` 단일 테이블만 걸고 items 등은
      별도 쿼리로 lazy/selectin 하도록 분리**해야 할 수 있음. 실제 적용 시 반드시
      `.with_for_update()` 추가 후 이 메서드를 쓰는 기존 호출부(`input_shipment`,
      `update_status`, `cancel_order`)가 다 정상 동작하는지 통합 테스트로 확인.
- [ ] `AdminOrderRepository`에 `increment_stock` 위임 메서드 추가 (1-0 결정에 따라
      `OrderRepository`와 별개로 자체 구현 — 동일한 2~3줄 SQL 중복 허용).

**TDD** (`tests/test_admin_order_service.py`):

1. `test_cancel_order_restores_stock`
   - Given: PAID 상태, items에 상품 X(quantity=1) 포함, 취소 사유 body 준비
   - When: `AdminOrderService.cancel_order(order_number, body)`
   - Then: fake repo의 `increment_stock` 호출 기록에 `(product_id, 1)` 존재
2. `test_cancel_order_not_cancellable_status_raises_and_no_stock_change`
   - Given: `status=SHIPPING` (취소 불가 상태)
   - When: 취소 시도
   - Then: `OrderCancelForbiddenError`, `increment_stock` 호출 없음
3. (통합 테스트, `tests/integration/test_admin_order_repository.py` 신규)
   `test_get_order_for_update_actually_locks_the_row` — 두 번째 트랜잭션이
   같은 order_number로 `get_order_for_update`를 호출하면 첫 트랜잭션 커밋까지
   대기하는지 (`asyncio.wait_for`로 타임아웃 짧게 걸어서 "블록됨"을 간접 확인하는
   패턴 — 실제 예시는 Task 5-2 테스트 설계와 동일한 기법 사용).

---

### 1-4. 결제 실패/취소 웹훅 수신 시 재고 복구 + 주문 상태 전환

**현재 코드** (`app/payment/payment_service.py:149-178`):
```python
async def handle_webhook(self, payload: TossWebhookPayload) -> None:
    if payload.event_type != _EVENT_PAYMENT_STATUS_CHANGED:
        return
    data = payload.data
    pg_tid: str | None = data.get("paymentKey")
    if not pg_tid:
        return
    payment = await self._repo.get_by_pg_tid(pg_tid)
    if payment is None:
        return
    if payment.status == PaymentStatus.PAID:
        return
    pg_status: str = data.get("status", "")
    if pg_status == _TOSS_DONE:
        payment.status = PaymentStatus.PAID
    elif pg_status in (_TOSS_CANCELED, _TOSS_PARTIAL_CANCELED):
        payment.status = PaymentStatus.CANCELLED
    elif pg_status == _TOSS_ABORTED:
        payment.status = PaymentStatus.FAILED
        payment.fail_reason = data.get("failure", {}).get("message")
```

**목표 코드** (ABORTED/CANCELED 분기에 order 조회 + 상태 전환 + 재고 복구 추가.
PAID 분기의 `order.status` 동기화는 **Task 3-1에서 별도로** 다룸 — 이 Task와
섞지 말 것, 커밋 단위를 작게 유지):

```python
    pg_status: str = data.get("status", "")
    if pg_status == _TOSS_DONE:
        payment.status = PaymentStatus.PAID
        # order.status 동기화는 Task 3-1에서 추가
    elif pg_status in (_TOSS_CANCELED, _TOSS_PARTIAL_CANCELED):
        payment.status = PaymentStatus.CANCELLED
        if pg_status == _TOSS_CANCELED:  # 부분취소는 전체 재고 복구 대상 아님
            await self._restore_order_stock_and_cancel(payment.order_id)
    elif pg_status == _TOSS_ABORTED:
        payment.status = PaymentStatus.FAILED
        payment.fail_reason = data.get("failure", {}).get("message")
        await self._restore_order_stock_and_cancel(payment.order_id)

async def _restore_order_stock_and_cancel(self, order_id: int) -> None:
    order = await self._repo.get_order_by_id(order_id)  # 신규 repo 메서드
    if order is None or order.status == OrderStatus.CANCELLED:
        return  # 이미 취소돼 있으면 중복 복구 방지
    for item in order.items:
        await self._repo.increment_stock(item.product_id, item.quantity)
    order.status = OrderStatus.CANCELLED
    order.cancelled_at = datetime.now(UTC)
```

- [ ] `PaymentRepository`에 `get_order_by_id(order_id: int) -> Order | None`
      추가 — `selectinload(Order.items)` 포함 (재고 복구에 items 필요).
- [ ] `PARTIAL_CANCELED`(부분 취소)는 **전체 재고 복구 대상이 아님**을 명시적으로
      분기 처리 (위 코드의 `if pg_status == _TOSS_CANCELED:` 조건). 이 모델에는
      라인별 부분 환불 개념이 아직 없으므로, 부분취소 시엔 재고를 만지지 않고
      `payment.status`만 `CANCELLED`로 바꿔두는 현재 동작을 **의도적으로 유지**한다 —
      다만 이건 실제로는 미완성 기능이므로 `# TODO: 부분 취소 시 라인별 재고 복구
      정책 미정` 주석을 남겨서 다음 세션이 헷갈리지 않게 할 것.
- [ ] `from datetime import UTC, datetime`가 이미 import돼 있는지 확인 (order_service.py에서
      쓰던 것과 동일 패턴).

**TDD** (`tests/test_payment_service.py`):

1. `test_webhook_aborted_cancels_order_and_restores_stock`
   - Given: `Order(status=PENDING)`, items 1개(product_id=1, quantity=2),
     `Payment(status=READY, pg_tid="pk_1")`, fake repo에 `get_order_by_id`/
     `increment_stock` 지원
   - When: `handle_webhook(payload)` with `data.status == "ABORTED"`
   - Then: `payment.status == FAILED`, `order.status == CANCELLED`,
     `increment_stock` 호출 기록에 `(1, 2)` 포함
2. `test_webhook_canceled_cancels_order_and_restores_stock`
   - 위와 동일하되 `status == "CANCELED"`
3. `test_webhook_partial_canceled_does_not_restore_stock`
   - Given: 동일 세팅
   - When: `status == "PARTIAL_CANCELED"`
   - Then: `payment.status == CANCELLED`, **`order.status`는 그대로 PENDING**,
     `increment_stock` 호출 없음 (현재 의도된 동작을 고정하는 회귀 테스트)
4. `test_webhook_aborted_already_cancelled_order_does_not_double_restore`
   - Given: `order.status`가 이미 `CANCELLED`인 상태에서 ABORTED 웹훅 재수신
     (웹훅은 재시도될 수 있으므로 현실적인 케이스)
   - When: `handle_webhook` 호출
   - Then: `increment_stock` 호출 없음 (중복 복구 방지 가드 확인)

---

## Task 2 — PENDING 주문 타임아웃 자동취소

### 2-0. 설계 결정 (구현 전 필수)

- [ ] **정책 확인**: `docs/요구사항정의서.md`에 결제 제한시간 명시가 있는지 먼저 확인.
      없으면 기본값 30분 제안하고 사용자 확인받을 것 — **구현 전에 반드시 확인, 임의로
      숫자를 정해서 하드코딩하지 말 것.**
- [ ] **방식 결정**: 두 옵션의 트레이드오프.

  | 방식 | 장점 | 단점 |
  |---|---|---|
  | 배치형 (스케줄러) | 정확한 시각에 취소, 사용자가 다시 보지 않아도 처리됨 | Celery/APScheduler 등 신규 인프라 도입 필요, MVP엔 과할 수 있음 |
  | 지연 평가형 | 인프라 추가 없음, 조회 시점에 즉시 체크 | 아무도 조회 안 하면 영원히 PENDING (재고는 여전히 묶임) |

  → **권장(MVP)**: 지연 평가형을 1차로 넣고, 최소한 **관리자 주문 목록 조회**와
  **재고가 임계치 이하인 상품의 재주문 시도(`create_order`)** 두 지점에서는
  만료된 PENDING을 즉시 정리하도록 한다 (재고가 실제로 필요한 순간에는 반드시
  정리되게). 완전한 배치형은 Phase 2로 미루고 `docs/todo.md`에 남긴다.
- [ ] **만료 기준 컬럼**: `Order.created_at + 임계값`으로 계산할지, 명시적
      `expires_at` 컬럼을 추가할지 결정. → **권장**: 지금은 컬럼 추가 없이
      `created_at` 기준 계산으로 시작 (마이그레이션 불필요, 되돌리기 쉬움).
      나중에 상품별/프로모션별로 제한시간이 달라지면 그때 컬럼화.

### 2-1. 지연 평가 로직 추가

- [ ] `app/order/order_service.py`에 모듈 레벨 상수
      `_PAYMENT_TIMEOUT = timedelta(minutes=30)` (또는 확정된 값) 추가.
- [ ] `OrderService`에 내부 헬퍼 추가:
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
- [ ] `get_order`(173-176), `list_orders`(161-169)에서 조회된 주문(들)에 대해
      `_expire_if_abandoned` 호출 — **주의**: `list_orders`는 N개를 반환하므로
      N번 호출이 되는데, 대부분 PENDING이 아니라 즉시 return되니 비용은 낮음.
      그래도 걱정되면 목록 조회 경로는 스킵하고 단건 조회(`get_order`)와
      `create_order`(재주문 시도) 두 곳만 우선 적용해도 됨 — 범위는 구현 시점에
      재량 판단.
- [ ] `AdminOrderService.get_order`/`list_orders`에도 동일 적용 검토 (관리자가
      먼저 발견하는 경우가 많으므로 우선순위 높음).

**TDD** (`tests/test_order_service.py`):

1. `test_get_order_expires_pending_order_past_timeout`
   - Given: `order.status = PENDING`, `order.created_at = datetime.now(UTC) - timedelta(minutes=31)`
   - When: `get_order(user_id, order_number)`
   - Then: 반환된 `OrderResponse.status == CANCELLED`, fake repo `increment_stock` 호출됨
2. `test_get_order_does_not_expire_pending_order_within_timeout`
   - Given: `created_at = now - timedelta(minutes=10)`
   - Then: 여전히 PENDING, 재고 변화 없음
3. `test_get_order_does_not_expire_non_pending_order`
   - Given: `status = PAID`, `created_at`은 아주 오래전
   - Then: 상태 변화 없음 (PAID는 타임아웃 대상 아님)

---

## Task 3 — 웹훅 ↔ 주문 상태 동기화 + `orderId` fallback 조회

### 3-1. 웹훅 PAID 처리 시 `order.status`도 전환

**현재 코드** (`app/payment/payment_service.py:171-173`):
```python
    if pg_status == _TOSS_DONE:
        payment.status = PaymentStatus.PAID
```

**목표 코드**:
```python
    if pg_status == _TOSS_DONE:
        payment.status = PaymentStatus.PAID
        order = await self._repo.get_order_by_id(payment.order_id)
        if order is not None and order.status == OrderStatus.PENDING:
            await self._repo.update_order_paid(order)
```

- [ ] `PaymentRepository.get_order_by_id`는 Task 1-4에서 이미 추가하기로 했으므로
      재사용. **Task 1-4와 Task 3-1은 같은 메서드를 공유하니, 구현 순서상 Task 1을
      먼저 끝내고 Task 3을 시작하면 자연히 중복이 없다.**
- [ ] `order.status == PENDING`일 때만 전환하는 가드 필수 — 이미 PAID/CANCELLED인
      주문에 웹훅이 늦게 도착하거나 재시도로 중복 도착해도 안전하게 무시됨.

**TDD** (`tests/test_payment_service.py`):

1. `test_webhook_done_transitions_order_to_paid`
   - Given: `Payment(status=READY, pg_tid="pk_1")`, `Order(status=PENDING)`
   - When: 웹훅 `status="DONE"`
   - Then: `payment.status == PAID`, `order.status == PAID`, `order.paid_at`이 채워짐
2. `test_webhook_done_on_already_paid_order_is_noop_for_order`
   - Given: `order.status`가 이미 `PAID`
   - When: 동일 웹훅 재수신 (멱등성 가드 `payment.status == PAID` → 조기 return이 이미
     165-166줄에 있으므로, 이 케이스는 사실 그 가드에서 먼저 걸릴 것 — **이 테스트로
     그 가드가 실제로 order 상태 변경 시도조차 안 하는지 확인**)
   - Then: 아무 것도 안 바뀜, 예외 없음
3. `test_webhook_done_order_already_missing_is_noop`
   - Given: `payment.order_id`가 가리키는 `Order`가 존재하지 않는 극단 상황(데이터
     정합성 깨짐 — 방어 코드 확인용)
   - Then: 예외 없이 조용히 지나감 (`order is not None` 가드 확인)

### 3-2. `pg_tid`로 못 찾으면 `orderId`로 fallback 조회

**현재 코드** (`app/payment/payment_service.py:158-165`):
```python
    data = payload.data
    pg_tid: str | None = data.get("paymentKey")
    if not pg_tid:
        return
    payment = await self._repo.get_by_pg_tid(pg_tid)
    if payment is None:
        return
```

**문제 시나리오 (구체적 타임라인)**:
1. `t=0`: 사용자가 토스 결제창에서 결제 완료 → 토스 서버가 승인 처리
2. `t=0.1s`: 사용자 브라우저가 성공 리다이렉트를 받는 도중 네트워크가 끊기거나 탭이
   닫힘 → 프론트가 우리 백엔드 `/payments/confirm`을 **호출하지 못함**
3. `t=0.1s`: 이 시점 우리 DB의 `Payment`는 여전히 `READY`, `pg_tid`는 `NULL`
   (confirm이 성공해야만 `pg_tid`가 채워짐 — `payment_repository.py:58`)
4. `t=2s`: 토스가 웹훅을 발송 (`paymentKey`, `orderId`, `status="DONE"` 포함)
5. `handle_webhook`이 `get_by_pg_tid(paymentKey)` 호출 → **아무 Payment도 못 찾음**
   (DB에 그 paymentKey를 가진 행이 없음, 애초에 저장된 적이 없으니까) → 조용히 `return`
6. **결과**: 토스는 결제를 승인했는데, 우리 시스템은 그 사실을 영원히 모른다.
   주문은 PENDING으로 남고, 사용자는 결제했는데 주문이 안 됐다고 오해하거나,
   Task 2의 타임아웃 로직이 나중에 이 주문을 취소해버려서 **결제는 됐는데 주문은
   취소되는 최악의 상황**까지 갈 수 있음.

**목표 코드**:
```python
    data = payload.data
    pg_tid: str | None = data.get("paymentKey")
    if not pg_tid:
        return

    payment = await self._repo.get_by_pg_tid(pg_tid)
    if payment is None:
        order_number: str | None = data.get("orderId")
        if not order_number:
            return
        payment = await self._repo.get_ready_payment_by_order_number(order_number)
        if payment is None:
            return
        # 이 시점 payment는 여전히 READY, pg_tid가 비어있는 상태 —
        # 아래 공통 로직에서 PAID 분기를 타면 pg_tid를 여기서 채워줘야 함.
```

- [ ] `PaymentRepository`에 `get_ready_payment_by_order_number(order_number: str) -> Payment | None`
      추가 — `Order`를 `order_number`로 찾고, 그 주문의 `payments` 중 `status == READY`인
      것 하나를 반환 (Task 5-1에서 "READY는 항상 최대 1개"가 보장되면 이 메서드가 훨씬
      단순해짐 — **Task 4/5를 먼저 끝내고 이 Task를 하면 모호함이 줄어든다**).
- [ ] fallback으로 찾은 `payment`가 PAID 분기를 탈 때, 원래 `update_status_paid`가
      하던 일(`pg_tid`, `paid_at`, 카드 정보 등 채우기)을 여기서도 해줘야 하는데,
      웹훅 payload에는 카드 정보가 confirm 응답과 다른 형태로 올 수 있음 — **토스
      웹훅 payload의 실제 필드 구조를 토스 공식 문서에서 재확인 필요** (이 프로젝트는
      아직 실제 토스 계약 전이라 목업 상태 — 실제 연동 시 반드시 실제 payload 샘플로
      필드명 재검증할 것). 최소한 `pg_tid`와 `paid_at`은 채우고, 카드 정보는 없으면
      `None`으로 둬도 영수증에는 confirm 경로보다 정보가 부실할 수 있음을 감안.
- [ ] `handle_webhook` 전체를 다시 정리하면 대략:
      ```python
      pg_status: str = data.get("status", "")
      if pg_status == _TOSS_DONE:
          payment.status = PaymentStatus.PAID
          payment.pg_tid = payment.pg_tid or pg_tid  # fallback 경로일 때만 채움
          order = await self._repo.get_order_by_id(payment.order_id)
          if order is not None and order.status == OrderStatus.PENDING:
              await self._repo.update_order_paid(order)
      ```

**TDD** (`tests/test_payment_service.py`):

1. `test_webhook_arrives_before_confirm_finds_payment_by_order_id_fallback`
   - Given: `Order(order_number="RK-1", status=PENDING)`,
     `Payment(status=READY, pg_tid=None)` — confirm이 아직 실행 안 된 상태
   - When: 웹훅 `data={"paymentKey": "pk_new", "orderId": "RK-1", "status": "DONE"}`
   - Then: 그 `Payment`가 `PAID`로 전환되고 `pg_tid == "pk_new"`, `order.status == PAID`
2. `test_webhook_fallback_when_no_ready_payment_and_no_pg_tid_match_is_noop`
   - Given: `orderId`에 해당하는 주문도 없거나, 있어도 READY 결제가 없음
   - Then: 예외 없이 조용히 return (다만 이 케이스는 로그를 남기는 게 운영상 필요 —
     **로깅 추가 여부를 이 작업에서 같이 검토**, `import logging` 후
     `logger.warning(...)` 형태로 최소 추가 권장)
3. `test_webhook_pg_tid_found_directly_does_not_use_fallback`
   - Given: 정상적으로 confirm이 먼저 끝나서 `pg_tid`가 이미 채워진 상태
   - When: 웹훅 도착
   - Then: `get_ready_payment_by_order_number`가 호출되지 않음 (fake repo에 호출
     카운터를 두고 0회 확인 — fallback 경로가 정상 경로를 방해하지 않는지 확인)

---

## Task 4 — `init_payment` 멱등성

**현재 코드** (`app/payment/payment_service.py:46-81`):
```python
async def init_payment(
    self, user_id: int, req: PaymentInitRequest
) -> PaymentInitResponse:
    order = await self._repo.get_order_by_number(req.order_number)
    if order is None or order.user_id != user_id:
        raise OrderNotFoundError()
    if order.status != OrderStatus.PENDING:
        raise PaymentFailedError(f"주문 상태가 PENDING 이 아닙니다: {order.status}")

    payment = Payment(
        order_id=order.id,
        pg_provider=PgProvider.TOSS,
        method=req.method,
        amount=order.total_amount,
        status=PaymentStatus.READY,
    )
    payment = await self._repo.save(payment)
    ...
    return PaymentInitResponse(...)
```

**문제**: 이 주문에 이미 `READY` 상태 `Payment`가 있는지 확인하지 않고 매번 새로
만든다. 사용자가 결제 페이지를 새로고침하거나 "결제하기" 버튼을 두 번 누르면
같은 주문에 대해 READY 행이 2개, 3개... 계속 쌓인다.

**목표 코드**:
```python
async def init_payment(
    self, user_id: int, req: PaymentInitRequest
) -> PaymentInitResponse:
    order = await self._repo.get_order_by_number(req.order_number)
    if order is None or order.user_id != user_id:
        raise OrderNotFoundError()
    if order.status != OrderStatus.PENDING:
        raise PaymentFailedError(f"주문 상태가 PENDING 이 아닙니다: {order.status}")

    existing_payments = await self._repo.get_by_order_id(order.id)
    ready_payment = next(
        (p for p in existing_payments if p.status == PaymentStatus.READY), None
    )
    if ready_payment is None:
        ready_payment = Payment(
            order_id=order.id,
            pg_provider=PgProvider.TOSS,
            method=req.method,
            amount=order.total_amount,
            status=PaymentStatus.READY,
        )
        ready_payment = await self._repo.save(ready_payment)

    customer_name = order.recipient_name
    return PaymentInitResponse(
        payment_id=ready_payment.id,
        order_number=order.order_number,
        amount=order.total_amount,
        customer_name=customer_name,
    )
```

- [ ] 위 변경 적용. **`method`가 재사용 시 요청값과 다르면 어떻게 할지 결정**:
      기존 READY 건의 `method`를 그대로 쓸지, 새 `req.method`로 갱신할지.
      → 권장: 기존 값을 유지 (결제수단을 바꾸고 싶으면 프론트가 먼저 그 READY를
      취소하는 별도 API가 필요하다는 뜻인데, 그건 이 문서 범위 밖. 지금은 "이미
      READY가 있으면 그대로 재사용"이 제일 단순하고 안전).
- [ ] 기존 `test_init_payment_success` 등 회귀 테스트가 "매번 새 Payment 생성"을
      전제로 하고 있는지 확인 — 전제가 깨지면 테스트 수정 필요 (아래 목록 참고).

**TDD** (`tests/test_payment_service.py`):

1. `test_init_payment_reuses_existing_ready_payment`
   - Given: 이미 `Payment(order_id=1, status=READY, id=99)`가 저장돼 있음
   - When: 같은 주문으로 `init_payment` 재호출
   - Then: 응답의 `payment_id == 99` (새로 생성되지 않음), fake repo의
     `save` 호출 카운터가 증가하지 않음
2. `test_init_payment_creates_new_when_no_ready_payment_exists` (기존 동작 회귀,
   이미 있는 `test_init_payment_success`가 이 역할을 하는지 확인하고 부족하면 보강)
3. `test_init_payment_ignores_paid_or_cancelled_payments_when_checking_ready`
   - Given: 그 주문에 `status=CANCELLED`인 과거 Payment가 있고 READY는 없음
   - Then: 새 READY Payment가 생성됨 (오래된 CANCELLED 건을 READY로 오인하지 않는지)

**기존 테스트 영향**: `tests/test_payment_service.py`의 `_FakePaymentRepo.save`가
지금은 항상 새 id를 부여하는 구조 — 이 Task 적용 후에도 "새로 저장하는 경우"의
동작은 그대로라 fake repo 자체는 수정 불필요. 다만 `init_payment` 호출부에서
`get_by_order_id`를 추가로 호출하므로, 그 메서드가 fake repo에 이미 있는지
확인(있음, 28-32 fake 구현 존재) — **수정 불필요, 재사용 가능.**

---

## Task 5 — `confirm_payment` 매칭/락/상태검증

### 5-1. `payment_key`로 정확한 READY 건 매칭

**현재 코드** (`app/payment/payment_service.py:101-107`):
```python
    payments = await self._repo.get_by_order_id(order.id)
    ready_payment = next(
        (p for p in payments if p.status == PaymentStatus.READY), None
    )
    if ready_payment is None:
        raise PaymentFailedError("결제 준비 중인 결제 건이 없습니다.")
```

**분석**: `pg_tid`(=payment_key)는 confirm 성공 **이후**에만 채워지므로, confirm
호출 시점엔 어떤 Payment 행에도 `req.payment_key`가 아직 저장돼 있지 않다 —
즉 지금 스키마로는 "정확히 이 payment_key에 대응하는 행"을 구조적으로 특정할
방법이 없다. 두 가지 해결책:

- **(a) API 계약 변경**: `init_payment` 응답의 `payment_id`를 프론트가 들고 있다가
  `PaymentConfirmRequest`에 `payment_id: int`를 추가해서 같이 보내게 한다.
  가장 정확하지만 프론트 변경이 필요하고, `payment_schemas.py`의
  `PaymentConfirmRequest`(29-38)에 필드 추가 + `payment_router.py`/프론트 SDK
  연동 코드까지 영향.
- **(b) Task 4 선행으로 문제 자체를 축소**: `init_payment`가 멱등해지면 정상
  흐름에서 주문당 READY는 항상 최대 1개이므로 "아무거나 집는" 문제가 사실상
  사라진다. API 변경 없음.

- [ ] **결정: (b)를 기본으로 채택.** Task 4 완료 후에도 동시성 상 READY가
      2개 이상 생기는 경로가 남아있는지 재검토 (예: `init_payment`의
      "READY 존재 확인 → 없으면 생성" 사이에 동시 요청 두 개가 끼어들면
      여전히 2개가 생길 수 있음 — **이건 Task 4의 원자성 문제이기도 함**,
      `init_payment`도 결국 `Order` 행을 잠그고 READY 확인+생성을 해야
      완전히 안전함. Task 4 구현 시 `get_order_by_number`를
      `with_for_update` 버전으로 바꾸는 걸 같이 검토할 것 — **Task 4 문서에
      이 내용 추가 필요, 아래 체크박스로 남김**).
  - [ ] (Task 4 보강) `init_payment`에서 `order` 조회를
        `get_order_by_number_with_lock`(신규, `FOR UPDATE`)으로 바꿔서
        "READY 확인 → 없으면 생성"이 원자적으로 처리되게 한다.
- [ ] (a)는 지금 채택하지 않지만, 나중에 여러 결제수단을 병렬로 시도하게
      하는 기능이 생기면 재검토가 필요하다는 점을 `docs/todo.md`에 각주로
      남길 것.

**TDD**: Task 4 완료 후 아래로 회귀 고정.
1. `test_confirm_payment_uses_the_single_ready_payment_after_init_dedup`
   - Given: Task 4가 적용된 `init_payment`를 두 번 호출해도 READY가 1개뿐인 상태
   - When: `confirm_payment` 호출
   - Then: 정상적으로 그 하나의 READY가 확정됨 (기존 happy path 테스트와 중복될
     수 있음 — 중복이면 새 테스트 추가하지 않고 기존 테스트에 주석으로 "Task 5-1
     회귀 커버" 표시만 해도 충분)

### 5-2. 동시 confirm 이중 호출 방지 (락)

**현재 코드**: `PaymentRepository.get_by_order_id`(28-32)는 락 없는 일반 SELECT.

**목표**: `confirm_payment`가 READY 결제를 조회하는 시점에 해당 `Payment` 행(또는
`Order` 행)을 잠그고, 잠근 뒤 다시 상태를 확인해서 이미 PAID면 외부 PG 호출
없이 바로 현재 상태를 반환(멱등 성공)하도록 만든다.

**목표 코드** (개략, 실제 시그니처는 구현 시 조정):
```python
# payment_repository.py
async def get_by_order_id_with_lock(self, order_id: int) -> list[Payment]:
    stmt = select(Payment).where(Payment.order_id == order_id).with_for_update()
    result = await self._session.execute(stmt)
    return list(result.scalars().all())
```
```python
# payment_service.py::confirm_payment
payments = await self._repo.get_by_order_id_with_lock(order.id)
ready_payment = next((p for p in payments if p.status == PaymentStatus.READY), None)
already_paid = next((p for p in payments if p.status == PaymentStatus.PAID), None)
if ready_payment is None:
    if already_paid is not None:
        # 이미 확정된 결제 — 멱등 성공으로 처리, 게이트웨이 재호출 안 함
        return PaymentConfirmResponse(
            order_number=order.order_number,
            status=already_paid.status,
            paid_at=already_paid.paid_at,
            card_company=already_paid.card_company,
            card_last4=already_paid.card_last4,
            installment_months=already_paid.installment_months,
        )
    raise PaymentFailedError("결제 준비 중인 결제 건이 없습니다.")
```
- [ ] 위 로직 적용. **`with_for_update()`가 걸린 채로 외부 PG API를 호출하는
      구간(`gateway.confirm`)이 있으므로, 락을 잡는 시점과 PG 호출 시점의
      순서를 신중하게 배치**: 락은 "이미 PAID인지 재확인"까지만 쓰고, PG
      호출 자체는 락을 잡은 트랜잭션 안에서 이뤄지되 이 트랜잭션이 오래 걸리면
      다른 요청이 오래 대기하게 됨 — Task 6에서 다루는 "네트워크 타임아웃"과
      맞물려서 락 대기시간이 늘어나는 부작용이 있을 수 있음. **일단은 정확성을
      우선하고, 실제 운영에서 락 대기가 문제가 되면 그때 "PG 호출은 락 밖에서,
      결과 반영만 락 안에서" 구조로 리팩터** (지금 단계에서 미리 최적화하지 않음
      — YAGNI).

**TDD** (`tests/test_payment_service.py`):

1. `test_confirm_payment_on_already_paid_order_is_idempotent_no_gateway_call`
   - Given: `Payment(status=PAID)`만 있고 READY는 없음(이미 확정된 상태)
   - When: 동일 주문으로 `confirm_payment` 재호출
   - Then: `PaymentConfirmResponse`가 기존 PAID 정보로 정상 반환되고,
     `_FakeGateway.confirm` 호출 카운터가 **증가하지 않음** (fake gateway에
     `self.call_count`류 카운터 필드 추가 필요)
2. `test_confirm_payment_concurrent_calls_only_one_gateway_call`
   (`tests/integration/test_payment_service.py` 신규 — 실제 DB 락 필요,
   `db_session` fixture 두 개를 각각 별도 트랜잭션처럼 써서 시뮬레이션하거나,
   `asyncio.gather`로 같은 서비스 인스턴스의 `confirm_payment`를 두 번 동시에
   호출해보고 `gateway.confirm` 총 호출 수가 1인지 확인 — 이 테스트는 실제
   Postgres 락 타이밍에 의존하므로 flaky할 위험이 있음, 실패 시 재실행 후에도
   깨지면 락 구현 자체를 재검토)

### 5-3. `confirm_payment`가 `order.status` PENDING 여부 검증

**현재 코드**: `confirm_payment`는 READY 결제 존재 + 금액 일치만 확인하고 진행 —
`order.status`가 PENDING인지 별도로 체크하지 않음.

**목표**: 5-2에서 "이미 PAID인 결제가 있으면 게이트웨이 호출 없이 반환"하는
가드를 넣으면 사실상 이 문제도 같이 해결되지만, **주문과 결제 상태가 어긋나는
데이터 이상 상태**(예: `payment.status=READY`인데 `order.status=CANCELLED`,
Task 2 타임아웃이 이 결제를 놔두고 주문만 취소해버린 경우)를 명시적으로
막는 방어 코드를 추가한다.

```python
if order.status != OrderStatus.PENDING:
    raise PaymentFailedError(f"주문 상태가 PENDING 이 아닙니다: {order.status}")
```
을 `confirm_payment` 맨 앞(READY 조회 전)에 추가.

- [ ] 위 가드 추가. **Task 2와의 상호작용 주의**: Task 2 타임아웃이 주문을
      취소하면서 READY 결제는 그대로 두면(현재 Task 2 설계에는 결제 자체를
      취소하는 로직이 없음 — Order만 CANCELLED), 사용자가 그 뒤에 실제로
      결제를 완료해서 confirm이 들어오면 이 가드에 막혀 `PaymentFailedError`가
      난다. **이건 의도된 동작** — 타임아웃으로 재고가 이미 풀려버린 주문에
      대한 결제는 받아주면 안 되므로, 이 케이스의 사용자 경험(에러 메시지로
      "주문이 취소되어 결제할 수 없습니다. 다시 주문해주세요" 안내)까지
      프론트와 맞출 필요는 있으나 백엔드 구현 자체는 이 가드로 충분.

**TDD**:
1. `test_confirm_payment_on_cancelled_order_raises`
   - Given: `order.status = CANCELLED` (예: Task 2 타임아웃으로 취소됨),
     READY 결제는 남아있는 상태
   - When: `confirm_payment` 호출
   - Then: `PaymentFailedError`, 게이트웨이 호출 없음
2. `test_confirm_payment_on_paid_order_is_idempotent` — 5-2의 1번과 사실상
   동일 케이스이므로 중복 작성하지 않고 5-2쪽 테스트로 통합해도 됨(구현 시 판단)

---

## Task 6 — confirm 네트워크 에러 시 상태 불명 케이스 처리

**현재 코드** (`app/payment/adapters/toss.py::confirm`, 25-63):
```python
async with httpx.AsyncClient(timeout=10.0) as client:
    resp = await client.post(_TOSS_CONFIRM_URL, json=payload, headers=headers)

if resp.status_code != 200:
    raise PaymentFailedError(f"Toss confirm 실패: {resp.status_code}")
```

**문제**: `client.post`가 타임아웃/커넥션 에러로 **예외를 던지면** (`httpx.TimeoutException`,
`httpx.ConnectError` 등) 지금 코드는 그걸 전혀 잡지 않는다 — 그대로 위로 전파돼서
`confirm_payment` 호출부에서 처리되지 않은 예외가 되고 (`PaymentFailedError`가 아닌
일반 예외라 `register_exception_handlers`의 `BusinessError` 핸들러가 못 잡음), 결국
FastAPI 기본 500 에러가 됨. **더 큰 문제는 의미론**: "PG가 명시적으로 거절함"과
"결과를 모름(타임아웃)"을 구분하지 않으면, 후속 처리(재시도 허용 여부, 사용자
안내 문구)가 잘못될 수 있다.

### 6-1. 신규 예외 클래스 추가

- [ ] `app/core/exceptions.py`에 `PaymentFailedError`(170-174) 근처에 추가:
      ```python
      class PaymentGatewayUnknownError(BusinessError):
          """PG 응답을 받지 못함 (타임아웃/네트워크 에러) — 결제 성공 여부 불명.

          사용자에게 재시도를 유도하면 안 된다 (이중 결제 위험). 웹훅이 최종
          진실을 알려줄 때까지 주문을 PENDING 으로 유지하고, 사용자에게는
          "결제 확인 중"이라고만 안내해야 한다.
          """

          code = "PAYMENT_GATEWAY_UNKNOWN"
          http_status = status.HTTP_502_BAD_GATEWAY
          message = "결제 결과를 확인할 수 없습니다. 잠시 후 주문 내역을 다시 확인해주세요."
      ```

### 6-2. `toss.py::confirm`에서 네트워크 예외 구분

```python
try:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(_TOSS_CONFIRM_URL, json=payload, headers=headers)
except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
    raise PaymentGatewayUnknownError() from exc

if resp.status_code != 200:
    raise PaymentFailedError(f"Toss confirm 실패: {resp.status_code}")
```

- [ ] 위 변경 적용. `httpx`의 정확한 예외 계층 확인 필요
      (`httpx.TransportError`가 `TimeoutException`/`ConnectError`/`NetworkError`의
      공통 상위 클래스이므로, **`except httpx.TransportError as exc:` 하나로
      단순화 가능** — 실제 httpx 버전의 예외 계층을 `python -c "import httpx;
      print(httpx.TransportError.__subclasses__())"`로 확인 후 반영).
- [ ] `confirm_payment`(payment_service.py)는 이 예외를 별도로 잡을 필요 없음 —
      `PaymentGatewayUnknownError`도 `BusinessError` 계열이라 그냥 위로
      전파되면 라우터의 공용 핸들러가 502로 응답. **다만 `order.status`가
      PENDING으로 남아있는지 명시적으로 확인하는 테스트는 필요** (아래).

### 6-3. Task 3(웹훅 동기화)가 최종 진실을 알려주는지 확인

- [ ] Task 3-1/3-2가 먼저 구현돼 있어야, 여기서 "타임아웃 났지만 실제로는 결제가
      성공한" 경우 웹훅이 도착했을 때 `orderId` fallback으로 찾아서 결국 PAID로
      정리된다 — **이 Task를 시작하기 전에 Task 3이 끝나 있는지 반드시 확인**.

**TDD**:

`tests/test_payment_service.py`:
1. `test_confirm_payment_gateway_timeout_raises_unknown_error_not_failed`
   - Given: fake gateway가 `httpx.TimeoutException` 계열을 시뮬레이션하도록
     `_FakeGateway`에 `should_timeout: bool` 옵션 추가하고, `confirm`에서
     `raise PaymentGatewayUnknownError()` (실제로는 adapter 레벨에서 나지만,
     서비스 단위 테스트에서는 gateway가 이 예외를 던지는 것까지 시뮬레이션)
   - When: `confirm_payment` 호출
   - Then: `PaymentGatewayUnknownError` 발생 (`PaymentFailedError`가 아님을
     명확히 구분해서 assert)
2. `test_confirm_payment_gateway_timeout_does_not_change_order_status`
   - Given: 위와 동일
   - Then: 예외 발생 후에도 `order.status == PENDING` 그대로 (재시도 가능한
     상태 유지 확인 — 여기서 절대로 `CANCELLED`나 다른 상태로 바뀌면 안 됨)

`tests/test_toss_adapter.py` (신규 — 이 어댑터 자체의 단위 테스트가 지금 없음.
`httpx`에 대한 실제 네트워크 호출 없이 검증하려면 `httpx.MockTransport` 또는
`respx` 라이브러리 사용 검토 — 신규 의존성 추가가 부담되면 `httpx.AsyncClient`를
패치하는 방식도 가능, 구현 시점에 프로젝트에 이미 있는 테스트 더블 관례를 따를 것):
1. `test_confirm_network_timeout_raises_gateway_unknown_error`
2. `test_confirm_4xx_response_raises_payment_failed_error` (기존 동작 회귀)
3. `test_confirm_200_response_parses_result_correctly` (기존 동작 회귀 — `card`
   정보가 없는 응답에 대한 방어도 같이 확인: `card_last4`가 빈 문자열일 때
   `"" [-4:] or None` 로직이 실제로 `None`을 반환하는지)

---

## Task 7 — 관리자 상품수정 동시성 (lost update 방지)

**현재 코드** (`app/catalog/admin_catalog_service.py::update_product`, 75-83):
```python
async def update_product(
    self, product_id: int, data: AdminProductUpdate
) -> AdminProductDetailResponse:
    product = await self._repo.get_by_id(product_id)
    if product is None:
        raise ProductNotFoundError()
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(product, key, value)
    return _to_detail(product)
```

`CatalogRepository.get_by_id`(`catalog_repository.py:74-79`)는 락 없는 일반 SELECT.
`AdminProductUpdate.stock`(스키마에 존재)이 포함된 PATCH 요청이 절대값으로
`setattr(product, "stock", value)`를 실행하면, 동시에 진행 중인 주문 생성
트랜잭션의 `FOR UPDATE` 차감분을 **완전히 무시하고 덮어쓸 수 있다** (lost update).

**목표**: `stock` 필드가 요청에 포함될 때만 락을 걸고 조회하도록 조건 분기.

```python
async def update_product(
    self, product_id: int, data: AdminProductUpdate
) -> AdminProductDetailResponse:
    changes = data.model_dump(exclude_unset=True)
    if "stock" in changes:
        product = await self._repo.get_by_id_with_lock(product_id)
    else:
        product = await self._repo.get_by_id(product_id)
    if product is None:
        raise ProductNotFoundError()
    for key, value in changes.items():
        setattr(product, key, value)
    return _to_detail(product)
```

- [ ] `CatalogRepository`에 `get_by_id_with_lock` 추가 (`get_by_id`와 동일하되
      `.with_for_update()` 추가).
- [ ] 위 서비스 로직 변경 적용.
- [ ] **범위 제한 결정 사항**: 이 방식도 "관리자가 절대값으로 stock을 정하면
      그 시점의 최신값 위에 계산해서 쓰는 게 아니라 그냥 그 값으로 덮어쓴다"는
      근본 설계는 그대로 유지 — 락은 "그 사이에 다른 트랜잭션이 끼어드는 것"만
      막아주는 것이고, "관리자가 입력한 값 자체가 최신 재고를 반영 못 한 stale
      값"인 문제는 여전히 남는다 (관리자가 화면을 연 시점과 PATCH를 보내는
      시점 사이에 주문이 여러 건 들어올 수 있음). **완전한 해결은 상대값
      조정 API(옵션 A, 문서 앞부분에 언급)뿐 — 이번엔 lost update의 "동시
      트랜잭션 덮어쓰기"만 막는 선에서 범위를 제한한다.** 이 한계를 주석으로
      명시.

**TDD** (`tests/integration/test_admin_catalog_service.py`, 신규 — 실제 DB
락 타이밍 검증이 필요하므로 fake repo로는 검증 불가):

1. `test_update_product_stock_change_blocks_until_order_transaction_commits`
   - Given: 상품 재고 10
   - When: (a) `create_order`용 세션이 그 상품을 `FOR UPDATE`로 잠근 채 대기 중일
     때, (b) 다른 세션에서 `update_product(stock=100)` 호출
   - Then: (b)가 (a)의 커밋/롤백까지 블록되는지 (타임아웃을 짧게 건 `asyncio.wait_for`로
     "블록됨"을 간접 확인) — 실제 구현 패턴은 Task 5-2 동시성 테스트와 동일 기법
2. `test_update_product_without_stock_field_does_not_lock`
   - `title`만 바꾸는 PATCH는 `get_by_id_with_lock`이 아니라 `get_by_id`가
     호출되는지 (fake/spy로 확인 가능한 단위 테스트로 충분, DB 불필요)

---

## Task 8 — 결제 금액 전달 시 서버 신뢰값(`order.total_amount`) 사용

**현재 코드** (`app/payment/payment_service.py:114-118`):
```python
result: TossConfirmResult = await self._gateway.confirm(
    payment_key=req.payment_key,
    order_id=req.order_id,
    amount=req.amount,
)
```

**목표 코드**:
```python
result: TossConfirmResult = await self._gateway.confirm(
    payment_key=req.payment_key,
    order_id=req.order_id,
    amount=order.total_amount,  # req.amount 는 검증에만 사용, 실제 전달은 서버 신뢰값
)
```

- [ ] 위 한 줄 변경. `req.amount == order.total_amount` 검증(109-112)이 이미
      있으므로 이 시점엔 두 값이 항상 같음 — **동작 변화는 없고, 원칙만
      바꾸는 순수 개선.**

**TDD**: 신규 테스트 불필요. 기존 `test_confirm_payment_success`,
`test_confirm_payment_amount_mismatch_raises`가 계속 통과하는지로 회귀 확인.
- [ ] 변경 후 `.venv/bin/pytest tests/test_payment_service.py -v` 전부 통과 확인.

---

## 검증된 것 — 조치 불필요 (회귀 테스트만 유지)

- **E-14**: 주문 금액과 결제 요청 금액 불일치 검증 (`confirm_payment` 109-112) — 정상.
- **E-16**: 웹훅 서명 검증 실패 시 400 반환 (`payment_router.py:90-91`) — 정상,
  토스가 400/500에는 재시도하고 200에는 재시도하지 않는 정책과 맞음.

이 두 항목은 각 Task 구현 중 실수로 깨지지 않았는지만 기존 테스트
(`test_confirm_payment_amount_mismatch_raises`, 웹훅 서명 관련 라우터 테스트가
있다면 그것)로 확인하면 된다. **별도 신규 작업 없음.**

---

## 진행 순서 권장 (재확인)

```
Task 1 (재고 복구) — 지금 바로 시작
   └─▶ Task 4 (init 멱등성, 5-1의 락 보강 포함)
          └─▶ Task 5 (confirm 매칭/락/상태검증)
                 └─▶ Task 3 (웹훅 동기화 + fallback)
                        └─▶ Task 6 (네트워크 에러 reconciliation)
Task 2 (타임아웃 자동취소) — Task 1 완료 후 언제든, 정책 결정(2-0)이 선행 조건
Task 7, 8 — 독립적, 나머지 완료 후 여유 있을 때
```

## 세션 재개 체크리스트

다음 세션 시작 시:
1. 이 파일에서 체크 안 된 첫 Task부터 확인.
2. `git status`/`git log`로 이미 반영된 코드가 있는지 실제 코드 기준으로
   재확인 (이 문서의 체크박스보다 코드가 진실 — 어긋나면 코드를 신뢰).
3. 각 Task 안의 "현재 코드" 스니펫이 실제 파일과 다르면(이전 Task로 이미
   변경됐을 수 있음), 그 Task를 시작하기 전에 실제 파일을 다시 읽고 스니펫을
   갱신할 것 — 이 문서의 스니펫은 2026-07-06 시점 기준이다.
4. CLAUDE.md의 게이트(`pytest`/`ruff check app tests`/`mypy app`)를 통과한
   상태에서만 다음 Task로 이동.
5. 커밋/푸시는 사용자가 명시적으로 요청할 때만 진행 (세션 규칙, 자동 커밋 금지).
