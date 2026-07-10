# 결제 PG 교체 — 토스페이먼츠 → 나이스페이(NICEPAY) 마이그레이션 작업 목록

> **배경**: 대행사를 하나만 쓰기로 하고 토스페이먼츠로 코드를 짰었는데(`testcase.md`,
> `testcase2.md` 전부 토스 기준), 가입비/연회비 조건 비교 끝에 **나이스페이로 PG를
> 교체**하기로 했다. 이 문서는 그 교체 작업을 TDD 단위로 세분화한 목록이다.
>
> **⚠️ 시작 전 필수 확인**: `docs/testcase2.md`를 처리하는 자동 루프
> (`scripts/run_testcase2_loop.sh`)가 다른 세션에서 **아직 돌고 있다면 반드시 먼저
> 중지할 것.** 그 문서의 Task 3(웹훅 락)/Task 4(웹훅 멱등성 가드)가 지금 이 문서와
> **동일한 파일**(`app/payment/payment_service.py`, `app/payment/payment_router.py`,
> `app/payment/payment_repository.py`)을 건드린다. 두 작업이 동시에 같은 파일을
> 고치면 충돌하거나 서로의 변경을 덮어쓸 수 있다.
>
> **권장 순서 (택1, 아래 "Task 0-1"에서 최종 결정)**:
> - (A) `testcase2.md`를 먼저 끝낸다(동시성/멱등성 버그는 PG가 뭐든 똑같이 존재하는
>   문제라 토스 코드 기준으로 고쳐두면 로직 자체는 나이스페이로 그대로 이식 가능) →
>   그 다음 이 문서로 PG를 교체한다.
> - (B) 이 문서를 먼저 진행해 PG부터 나이스페이로 바꾸고, 그 위에서
>   `testcase2.md`의 동시성/멱등성 수정을 나이스페이 기준으로 다시 적용한다
>   (`testcase2.md`의 Task 3/4 스니펫은 토스 필드명 기준이라 그대로 못 쓰고
>   재작성 필요).
>
> **작성일**: 2026-07-10

---

## 0. 현재 코드 전수조사 — 토스 전용 코드가 있는 파일 목록

| 파일 | 토스 종속 내용 |
|---|---|
| `app/payment/adapters/toss.py` | `TossPaymentGateway` 전체 (confirm URL, Basic Auth, HMAC 웹훅 검증) |
| `app/payment/adapters/ports.py` | `TossConfirmResult` 데이터클래스(이름부터 Toss 전용), `PaymentGateway` Protocol |
| `app/payment/adapters/fake.py` | `FakePaymentGateway` — `TossConfirmResult` 반환 (이름만 종속, 로직은 PG 무관) |
| `app/payment/payment_schemas.py` | `TossWebhookPayload`(`eventType`/`data` 봉투 구조), `PaymentConfirmRequest`(`payment_key`=paymentKey, `order_id`=orderId 필드명이 토스 명명 그대로) |
| `app/payment/payment_service.py` | `_TOSS_DONE`/`_TOSS_CANCELED`/`_TOSS_PARTIAL_CANCELED`/`_TOSS_ABORTED` 상수, `handle_webhook`의 `pg_status` 분기 전체, `_EVENT_PAYMENT_STATUS_CHANGED` |
| `app/payment/payment_router.py` | `POST /payments/webhooks/toss` 경로, `TossPayments-Signature` 헤더 읽기, `TossWebhookPayload` 타입 |
| `app/payment/models.py` | `PgProvider.TOSS/KAKAO/NAVER` enum, `PaymentMethod.TOSS_PAY` |
| `app/core/config.py:72` | `toss_secret_key: str | None = None` |
| `app/core/deps.py:247-260` | `get_payment_service`가 `TossPaymentGateway` import/생성 |
| `.env.example:56-60` | `TOSS_CLIENT_KEY`(주의: `Settings`에 정의 안 돼 있어 실제로는 안 읽힘 — 죽은 값), `TOSS_SECRET_KEY`, `USE_FAKE_PG` |
| `tests/test_toss_adapter.py` | 전체 — 토스 응답 포맷 기준 |
| `tests/test_payment_service.py` | 웹훅 관련 테스트 전부(`data={"paymentKey":..., "status": "DONE"}` 등 토스 필드명) |
| `docs/testcase.md`, `docs/testcase2.md` | 문서 전체가 토스 필드명/이벤트값 기준 — 코드는 아니지만 참고 시 주의 |

**건드리면 안 되는 것**: `.env.example:63`의 `IDENTITY_PROVIDER=toss`는 **본인인증**(휴대폰 인증)
용이고 결제 PG와 무관한 별도 계약이다. 이 마이그레이션 범위 밖 — 손대지 않는다.

---

## 1. 나이스페이 API 레퍼런스 (조사 완료, 구현 시 그대로 참조)

> 출처: `github.com/nicepayments/nicepay-manual`(공식 저장소), `developers.nicepay.co.kr`.
> 로컬에 `nicepay-docs` MCP(`~/.claude/mcp-servers/nicepay-mcp`)로 문서 인덱싱 되어 있으니
> 구현 중 세부사항이 더 필요하면 그걸로 재검색할 것. 도메인/서명 계산식은 실제 계약 후
> 샌드박스 키로 한 번 더 검증 필수(문서와 실제 응답이 다를 가능성 있음).

### 1-1. 결제창 호출 (JS SDK, 프론트엔드 — 백엔드 작업 범위 밖이지만 계약 이해용)

```html
<script src="https://pay.nicepay.co.kr/v1/js/"></script>
<script>
AUTHNICE.requestPay({
  clientId: 'af0d116236df437f831483ee9c500bc4',
  method: 'card',                 // card, bank, vbank, cellphone, naverpay, kakaopay ...
  orderId: 'your-unique-orderid', // = 우리 order_number
  amount: 1004,
  goodsName: '나이스페이-상품',
  returnUrl: 'http://localhost:4567/serverAuth'
});
</script>
```

### 1-2. 인증 완료 콜백 (`returnUrl`로 **POST** 전송 — 토스와 가장 큰 구조적 차이)

토스는 프론트가 success 리다이렉트의 **쿼리스트링**으로 `paymentKey`/`orderId`/`amount`를
받아서 그걸 그대로 우리 `/payments/confirm`에 body로 실어 보내는 구조였다. 나이스페이는
**`returnUrl`로 브라우저가 form POST를 직접 쏜다** — 프론트 SPA가 fetch로 가로챌 수 있는
GET 리다이렉트가 아니라 실제 폼 제출이다. 이게 Task 10의 설계 결정 포인트.

`returnUrl`로 오는 POST 바디(`application/x-www-form-urlencoded`):

| 필드 | 설명 |
|---|---|
| `authResultCode` | `0000`=성공, 그 외 실패코드 |
| `authResultMsg` | 인증결과 메시지 |
| `tid` | 결제 인증 키 — **토스의 `paymentKey`에 대응**, 성공 시만 내려옴 |
| `clientId` | 가맹점 식별코드 |
| `orderId` | 우리 `order_number` |
| `amount` | 결제 금액 |
| `authToken` | 인증 TOKEN — 승인 API 호출 전 위변조 검증용 |
| `signature` | `hex(sha256(authToken + clientId + amount + SecretKey))` |
| `mallReserved` | 상점 예약 필드 |

### 1-3. 서버 승인(approve) API — 토스의 `confirm`에 대응

```
POST /v1/payments/{tid} HTTP/1.1
Host: api.nicepay.co.kr          (샌드박스: sandbox-api.nicepay.co.kr)
Authorization: Basic <base64(ClientKey:SecretKey)>   (또는 Bearer <accessToken>)
Content-Type: application/json;charset=utf-8

{
  "amount": 1004,
  "ediDate": "...",              // 선택, ISO 8601 전문생성일시
  "signData": "..."              // 선택, hex(sha256(tid + amount + ediDate + SecretKey))
}
```

**응답**:

| 필드 | 설명 |
|---|---|
| `resultCode` | `0000`=성공 |
| `resultMsg` | 결과 메시지 |
| `tid` | 결제 승인 키 (= `Payment.pg_tid`) |
| `orderId` | 우리 `order_number` |
| `status` | `paid` / `ready` / `failed` / `cancelled` / `partialCancelled` / `expired` |
| `paidAt` / `failedAt` / `cancelledAt` | ISO 8601 |
| `amount` | 결제 금액 |
| `balanceAmt` | 취소 가능 잔액 |
| `payMethod` | `card` / `vbank` / `naverpay` / `kakaopay` 등 |
| `card.cardCode` / `card.cardName` / `card.cardNum`(마스킹) / `card.cardQuota` / `card.isInterestFree` | 카드 정보 |
| `vbank.vbankCode` / `vbankName` / `vbankNumber` / `vbankExpDate` / `vbankHolder` | 가상계좌 정보 |

**⚠️ 확인 필요(샌드박스 테스트로 검증할 것)**: 토스의 `card.approveNo`(카드 승인번호,
`Payment.approval_number`에 저장 중)에 대응하는 필드가 이 응답 스펙에 명시적으로 안
보인다. 실제 응답을 받아보고 어느 필드가 승인번호인지 확인 필요 — Task 3에서 처리.

### 1-4. 웹훅(Webhook/Notification)

- **요청**: 등록된 Endpoint로 `POST`, `Content-Type: application/json;charset=utf-8`
- **응답 요구사항(★토스와 다름★)**: `HTTP 200` + **바디에 정확히 `"OK"` 문자열**을
  `text/html;charset=utf-8`로 반환해야 함. 토스는 그냥 `{"status":"ok"}` JSON을
  200으로 반환하면 됐지만, 나이스페이는 바디 내용까지 검사한다 — 이거 안 지키면
  나이스페이가 "실패"로 간주하고 재전송한다.
- **발송 시점**: 결제 승인 완료, 가상계좌 발급, 가상계좌 입금, 결제 취소(API/관리자)
- **페이로드** (flat JSON — 토스처럼 `eventType`+`data` 봉투 구조가 아님):

| 필드 | 설명 |
|---|---|
| `resultCode` / `resultMsg` | 결과 |
| `tid` | 결제 승인 키 |
| `orderId` | 우리 `order_number` |
| `status` | `paid`/`ready`/`failed`/`cancelled`/`partialCancelled`/`expired` |
| `amount` / `balanceAmt` | 금액 / 취소가능잔액 |
| `payMethod` | `card`/`vbank`/`bank`/`cellphone`/`naverpay`/`kakaopay`/`samsungpay` |
| `paidAt` / `cancelledAt` | ISO 8601 |
| `signature` | `hex(sha256(tid + amount + ediDate + SecretKey))` — **바디 안에 서명이 포함**돼 있음. 토스처럼 별도 HTTP 헤더(`TossPayments-Signature`)가 아니다 |

**서명 계산에 `ediDate`가 필요한데 웹훅 페이로드 필드 표에는 `ediDate`가 명시 안 돼
있음** — 실제 페이로드에 `ediDate`가 포함되는지 샌드박스로 확인 필요(Task 4).

### 1-5. 결제 취소(cancel) API

```
POST /v1/payments/{tid}/cancel HTTP/1.1
Authorization: Basic <base64(ClientKey:SecretKey)>
Content-Type: application/json;charset=utf-8

{
  "reason": "취소 사유",
  "orderId": "merchant-order-id",   // 필수, 부분취소 시 같은 orderId 중복 호출 불가
  "cancelAmt": 1000                 // 생략 시 전액취소
}
```

응답: `resultCode`, `resultMsg`, `tid`(원거래), `cancelledTid`(취소거래), `status`,
`cancelledAt`.

**참고**: 현재 코드베이스엔 PG 취소 API를 호출하는 곳이 **어디에도 없다**
(`OrderService.cancel_order`/`request_refund`는 우리 DB 상태만 바꾸고 PG는 안 건드림
— `testcase.md` Task 1-2 문서에도 "PG 환불은 범위 밖"이라 명시돼 있음). 이 API 연동
자체를 이번에 새로 추가할지는 Task 9에서 결정.

### 1-6. 인증

- **Basic Auth**: `Authorization: Basic base64(ClientKey:SecretKey)`
- **Bearer(대안)**: `POST /v1/access-token`(Basic Auth로 발급, 유효기간 30분) →
  `Authorization: Bearer <token>`. MVP는 매 요청 Basic Auth로 충분 — 토큰 캐싱 등
  최적화는 트래픽 늘어나면 그때(YAGNI, `testcase.md`의 톤과 동일한 원칙).
- **도메인**: 운영 `api.nicepay.co.kr`, 샌드박스 `sandbox-api.nicepay.co.kr`(v1 경로
  공통) — `nicepay-mcp` 리드미에서도 동일 도메인 확인됨.

---

## 우선순위 요약

| # | Task | 심각도/순서 | 선행 조건 |
|---|---|---|---|
| 0 | 마이그레이션 전 결정사항 확정 | 필수, 최우선 | 없음 |
| 1 | 환경설정 교체 | ★★★ | Task 0 |
| 2 | `ports.py` 재설계 | ★★★ | Task 0 |
| 3 | `NicePayPaymentGateway` 어댑터 구현 | ★★★ | Task 2, 샌드박스 키 |
| 4 | 웹훅 스키마/서명검증 재작성 | ★★★ | Task 2, 샌드박스 키 |
| 5 | `payment_router.py` 변경 | ★★☆ | Task 3, 4 |
| 6 | `payment_service.py` 이벤트 분기 재작성 | ★★★ | Task 4 |
| 7 | 모델 enum 정리 | ★★☆ | 없음 (독립적) |
| 8 | `FakePaymentGateway` 정합성 확인 | ★☆☆ | Task 2 |
| 9 | 취소(cancel) API 연동 여부 결정/구현 | ★☆☆ | Task 3 (신규 기능, 범위 밖으로 뺄 수도 있음) |
| 10 | 프론트 연동 계약 변경(`returnUrl`) | ★★★ | Task 3 |
| 11 | 기존 테스트 전수 이관 | ★★★ | Task 3~7 완료 후 |
| 12 | `testcase.md`/`testcase2.md` 관계 정리 | 필수 | 전체 완료 후 |

---

## Task 0 — 마이그레이션 전 결정사항 (구현 착수 전 필수)

- [ ] **결정 0-1**: `testcase2.md` 루프 처리 순서 — 이 문서 맨 위 "시작 전 필수 확인"의
      (A)/(B) 중 선택. **다른 세션의 루프가 지금 돌고 있는지부터 확인**
      (`ps aux | grep run_testcase2_loop`, 또는 그 세션에 직접 물어볼 것).
- [ ] **결정 0-2**: 나이스페이 계약 상태 확인 — 샌드박스 Client Key/Secret Key를
      실제로 발급받았는지. 없으면 Task 3/4/9는 스펙만 보고 구현하고 실동작 검증은
      키 발급 후로 미룬다(문서 1절의 "⚠️ 확인 필요" 항목들이 특히 이 검증 없이는
      확신할 수 없음).
- [ ] **결정 0-3**: `returnUrl`을 백엔드 엔드포인트로 둘지, 프론트 라우트로 둘지
      (Task 10에서 상세 설계 — 지금은 방향만 정함).
- [ ] **결정 0-4**: 결제수단(PaymentMethod) enum의 `TOSS_PAY` 값 처리 — 나이스페이가
      토스페이 지갑을 간편결제 수단으로 실제 지원하는지 계약 시 확인. 지원 안 하면
      `TOSS_PAY` 제거하고 `PAYCO`/`SAMSUNG_PAY` 등 나이스페이가 실제 제공하는 수단으로
      교체(Task 7).
- [ ] **결정 0-5**: 기존에 이미 쌓인 `Payment.pg_provider = 'TOSS'` 레코드(있다면)를
      어떻게 할지 — 운영 전이라 실데이터 없으면 무관하게 스킵 가능. 실데이터가 있다면
      과거 데이터는 `TOSS`로 유지하고 이후 신규 결제만 `NICEPAY`로 저장(컬럼이
      `native_enum=False`라 DB 마이그레이션 없이 Python enum에 값 추가만 하면 됨 —
      Alembic revision 불필요, 아래 Task 7 참고).

---

## Task 1 — 환경설정 교체

**현재** (`app/core/config.py:72-75`):
```python
toss_secret_key: str | None = None
# True 로 설정하면 TossPaymentGateway 대신 FakePaymentGateway 를 사용.
use_fake_pg: bool = False
```

**목표**:
```python
nicepay_client_key: str | None = None
nicepay_secret_key: str | None = None
# True 로 설정하면 NicePayPaymentGateway 대신 FakePaymentGateway 를 사용.
use_fake_pg: bool = False
```

- [ ] `app/core/config.py`: `toss_secret_key` → `nicepay_client_key` + `nicepay_secret_key`
      (승인 API의 Basic Auth가 Client Key + Secret Key 조합이라 토스 때와 달리 **키가
      2개** 필요 — `toss_secret_key` 하나였던 것과 다름, 빠뜨리기 쉬운 지점).
- [ ] `.env.example:56-60` 교체:
      ```
      # 나이스페이(NICEPAY)
      NICEPAY_CLIENT_KEY=
      NICEPAY_SECRET_KEY=
      # PG 미연동 개발 단계에서 결제를 항상 성공시키려면 true (운영에서는 반드시 false)
      USE_FAKE_PG=false
      ```
      **CLAUDE.md 규칙 준수**: 새 변수는 `config.py` / `.env.example` / 본인 `.env`
      3곳 동시 수정 — 민감값이라 `.env.example`엔 default 비워둠.
- [ ] 본인 `.env`에도 실제 값(또는 빈 값 유지) 반영 — 이건 사용자가 직접, 커밋 대상 아님.

**TDD**: 설정값 자체는 pydantic-settings 필드 추가라 별도 유닛 테스트 불필요.
`get_payment_service`가 새 필드를 정상 참조하는지는 Task 3 통합에서 자연히 검증됨.

---

## Task 2 — `ports.py` 재설계

**현재** (`app/payment/adapters/ports.py`):
```python
@dataclass
class TossConfirmResult:
    method: str
    pg_tid: str
    paid_at: datetime
    card_company: str | None
    card_last4: str | None
    installment_months: int
    approval_number: str | None


class PaymentGateway(Protocol):
    async def confirm(self, *, payment_key: str, order_id: str, amount: int) -> TossConfirmResult: ...
    def verify_webhook_signature(self, body: bytes, signature: str) -> bool: ...
```

**설계 결정**: `TossConfirmResult`라는 이름 자체가 특정 PG에 종속돼 있다 — 이번 기회에
`PgConfirmResult`로 이름을 바꿔서 진짜로 "PG 무관 Protocol"이 되게 한다. `PaymentGateway`
Protocol의 메서드 시그니처(`confirm(payment_key, order_id, amount)`,
`verify_webhook_signature(body, signature)`)는 **필드 개념 자체는 나이스페이에도 그대로
적용 가능**(`payment_key`=`tid`, `signature`는 여전히 문자열) — Protocol 자체는 안 바꿔도
됨. 단, `verify_webhook_signature`의 `signature` 인자가 토스는 HTTP 헤더에서 왔지만
나이스페이는 **바디 안의 `signature` 필드**에서 온다 — 호출부(Task 5, router)에서
어디서 뽑아오는지만 달라지고 Protocol 시그니처는 유지 가능.

**목표 코드**:
```python
@dataclass
class PgConfirmResult:
    """PG 승인 결과. gateway.confirm() 이 반환하는 DTO. PG 무관 공통 필드."""

    method: str
    pg_tid: str
    paid_at: datetime
    card_company: str | None
    card_last4: str | None
    installment_months: int
    approval_number: str | None


class PaymentGateway(Protocol):
    """PG 어댑터 인터페이스. Toss / NICEPAY / KG이니시스 교체 가능."""

    async def confirm(
        self, *, payment_key: str, order_id: str, amount: int
    ) -> PgConfirmResult: ...

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool: ...
```

- [ ] `TossConfirmResult` → `PgConfirmResult` 리네임(`replace_all`). 영향 범위:
      `payment_service.py`(타입 힌트 import), `adapters/toss.py`(있다면 삭제 대상,
      Task 3에서 어댑터 자체를 교체), `adapters/fake.py`, `tests/test_payment_service.py`,
      `tests/test_toss_adapter.py`(삭제 예정).
- [ ] `app/payment/adapters/ports.py` 파일 자체를 `app/payment/adapters/ports.py`
      그대로 유지할지, `pg_ports.py`로 리네임할지도 고려(파일명도 `toss` 언급은
      없으니 유지해도 무방 — **과잉 리네임 지양**, 파일명 자체는 안 바꾸는 쪽 권장).

**TDD**: 이름 변경은 리팩터라 별도 Red 불필요 — 전체 `pytest` 회귀로 참조 누락(ImportError)
없는지 확인.

---

## Task 3 — `NicePayPaymentGateway` 어댑터 구현

**참고**(`app/payment/adapters/toss.py` 전체, 대체될 기존 코드):
```python
class TossPaymentGateway:
    async def confirm(self, *, payment_key: str, order_id: str, amount: int) -> TossConfirmResult:
        secret_key = getattr(settings, "toss_secret_key", "") or ""
        ...
        encoded = base64.b64encode(f"{secret_key}:".encode()).decode()
        headers = {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}
        payload = {"paymentKey": payment_key, "orderId": order_id, "amount": amount}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_TOSS_CONFIRM_URL, json=payload, headers=headers)
        ...
```

**목표 코드** (신규 `app/payment/adapters/nicepay.py`, 기존 `toss.py`는 삭제):
```python
"""NICEPAY 어댑터. PaymentGateway Protocol 구현체."""

from __future__ import annotations

import base64
import hashlib

import httpx

from app.core.config import settings
from app.core.exceptions import PaymentFailedError, PaymentGatewayUnknownError
from app.payment.adapters.ports import PgConfirmResult

_NICEPAY_API_BASE = "https://api.nicepay.co.kr"  # 샌드박스: sandbox-api.nicepay.co.kr
_RESULT_CODE_SUCCESS = "0000"


class NicePayPaymentGateway:
    """나이스페이 REST API(v1) 어댑터."""

    def _auth_header(self) -> dict[str, str]:
        client_key = getattr(settings, "nicepay_client_key", "") or ""
        secret_key = getattr(settings, "nicepay_secret_key", "") or ""
        if not client_key or not secret_key:
            raise PaymentFailedError("NICEPAY 인증 키가 설정되지 않았습니다.")
        encoded = base64.b64encode(f"{client_key}:{secret_key}".encode()).decode()
        return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json;charset=utf-8"}

    async def confirm(
        self, *, payment_key: str, order_id: str, amount: int
    ) -> PgConfirmResult:
        # payment_key == tid (나이스페이 용어)
        url = f"{_NICEPAY_API_BASE}/v1/payments/{payment_key}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url, json={"amount": amount}, headers=self._auth_header()
                )
        except httpx.TransportError as exc:
            raise PaymentGatewayUnknownError() from exc

        data = resp.json()
        if resp.status_code != 200 or data.get("resultCode") != _RESULT_CODE_SUCCESS:
            raise PaymentFailedError(
                f"NICEPAY 승인 실패: {data.get('resultCode')} {data.get('resultMsg')}"
            )

        card = data.get("card") or {}
        from datetime import datetime
        return PgConfirmResult(
            method=data.get("payMethod", ""),
            pg_tid=data["tid"],
            paid_at=datetime.fromisoformat(data["paidAt"]),
            card_company=card.get("cardName"),
            card_last4=(card.get("cardNum") or "")[-4:] or None,  # ⚠️ Task 3-검증: 마스킹 형식 확인 필요
            installment_months=int(card.get("cardQuota") or 0),
            approval_number=None,  # ⚠️ Task 3-검증: 응답에 승인번호 상당 필드가 없음, 샌드박스로 확인
        )

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        # Task 4 에서 구현 — 바디를 파싱해서 tid/amount/ediDate 로 서명 재계산해야 하므로
        # HMAC 단순 비교였던 토스 방식과 다르다. 여기 스텁만 남기고 Task 4 로 이관.
        raise NotImplementedError
```

- [ ] `app/payment/adapters/nicepay.py` 신규 생성 (`confirm` 부분만 우선 — `verify_webhook_signature`는 Task 4).
- [ ] `card_last4` 추출 로직 — 나이스페이 `cardNum`이 토스처럼 "뒤 4자리만 노출"인지,
      아니면 다른 마스킹 패턴(`1234-56**-****-7890` 등)인지 실제 응답으로 확인 후
      슬라이싱 로직 조정 (샌드박스 결제 1건 찍어보고 확인 — Task 3 완료 조건에 포함).
- [ ] `approval_number` — 실제 응답 JSON 전체를 로그로 찍어서 승인번호에 해당하는
      필드가 있는지 확인. 없으면 `Payment.approval_number`를 nullable로 두고 그냥
      `None` 저장(모델은 이미 `nullable=True`라 스키마 변경 불필요).
- [ ] `app/payment/adapters/toss.py` 삭제.
- [ ] `app/core/deps.py:247-260` 교체:
      ```python
      async def get_payment_service(
          session: AsyncSession = Depends(db_session),
          email_sender: EmailSender = Depends(get_email_sender),
      ) -> PaymentService:
          gateway: PaymentGateway
          if settings.use_fake_pg:
              from app.payment.adapters.fake import FakePaymentGateway
              gateway = FakePaymentGateway()
          else:
              from app.payment.adapters.nicepay import NicePayPaymentGateway
              gateway = NicePayPaymentGateway()
          return PaymentService(PaymentRepository(session), gateway, email_sender)
      ```

**TDD** (`tests/test_nicepay_adapter.py`, 신규 — `tests/test_toss_adapter.py` 대체):
1. `test_confirm_200_response_parses_result_correctly`
   - Given: `httpx.MockTransport`(또는 기존 프로젝트 관례)로 `resultCode="0000"`,
     `tid`, `payMethod="card"`, `paidAt`, `card` 객체 포함 응답 mock
   - Then: `PgConfirmResult` 필드가 정확히 매핑되는지
2. `test_confirm_non_zero_result_code_raises_payment_failed_error`
   - Given: `resultCode="4000"`(실패코드) mock 응답, HTTP 200이어도 실패로 처리돼야 함
     (⚠️ 토스는 HTTP status code만 보면 됐는데 나이스페이는 **HTTP 200이어도
     `resultCode`가 실패일 수 있다** — 이 구분을 놓치면 실패 결제를 성공으로 처리하는
     심각한 버그가 됨. 반드시 회귀 테스트로 고정)
3. `test_confirm_network_timeout_raises_gateway_unknown_error` (기존 토스 테스트와 동일 취지)
4. `test_confirm_connect_error_raises_gateway_unknown_error`
5. `test_confirm_card_last4_extraction_matches_actual_masking_format`
   - 샌드박스 실응답 캡처 후 작성 (Task 3 검증 항목과 연계 — 실제 포맷 확인 전엔
     placeholder로 토스와 동일 가정하고, 확인되면 갱신)

---

## Task 4 — 웹훅 스키마 신규 작성 + 서명 검증 재작성

**현재** (`app/payment/payment_schemas.py`):
```python
class TossWebhookPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    event_type: str = Field(alias="eventType")
    data: dict[str, Any]
```

**목표 코드**:
```python
class NicePayWebhookPayload(BaseModel):
    """POST /payments/webhooks/nicepay — 나이스페이 웹훅 바디.

    토스와 달리 eventType/data 봉투가 없는 flat 구조. signature 도 헤더가 아니라
    바디 안에 포함된다.
    """

    model_config = ConfigDict(populate_by_name=True)

    result_code: str = Field(alias="resultCode")
    result_msg: str = Field(alias="resultMsg")
    tid: str
    order_id: str = Field(alias="orderId")
    status: str  # paid/ready/failed/cancelled/partialCancelled/expired
    amount: int
    balance_amt: int | None = Field(default=None, alias="balanceAmt")
    pay_method: str | None = Field(default=None, alias="payMethod")
    paid_at: str | None = Field(default=None, alias="paidAt")
    cancelled_at: str | None = Field(default=None, alias="cancelledAt")
    edi_date: str | None = Field(default=None, alias="ediDate")  # ⚠️ 실제 포함 여부 확인 필요
    signature: str
```

- [ ] `TossWebhookPayload` 삭제, `NicePayWebhookPayload` 추가.
- [ ] **서명 검증 로직** — `PaymentGateway.verify_webhook_signature(body: bytes, signature: str) -> bool`
      Protocol은 유지하되, 나이스페이 구현은 raw HMAC이 아니라 **바디를 JSON 파싱해서
      `tid`+`amount`+`ediDate`+SecretKey로 재계산 후 비교**해야 한다:
      ```python
      def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
          import json
          secret_key = getattr(settings, "nicepay_secret_key", "") or ""
          if not secret_key:
              return False
          try:
              payload = json.loads(body)
          except json.JSONDecodeError:
              return False
          tid = payload.get("tid", "")
          amount = payload.get("amount", "")
          edi_date = payload.get("ediDate", "")  # ⚠️ 실제 필드명/포함 여부 샌드박스 확인
          raw = f"{tid}{amount}{edi_date}{secret_key}"
          expected = hashlib.sha256(raw.encode()).hexdigest()
          return hmac.compare_digest(expected, signature)
      ```
      **호출부(`Protocol`) 시그니처를 유지하기 위해 `signature` 인자는 라우터가 이미
      파싱된 JSON에서 `payload["signature"]`를 뽑아 넘긴다** — 토스처럼 HTTP 헤더가
      아니므로 라우터 쪽 구현이 달라짐 (Task 5).
- [ ] `ediDate`가 실제 웹훅 바디에 없다면(문서에 명시가 안 돼 있어 확인 필요) 서명
      계산식 자체가 달라져야 함 — 샌드박스 웹훅 1건 실제로 받아서 전체 필드 로그를
      찍어보고 이 Task 완료 조건에 반영.

**TDD** (`tests/test_nicepay_adapter.py`에 이어서, 또는 별도 `verify_webhook_signature` 섹션):
1. `test_verify_webhook_signature_valid_returns_true`
   - Given: 알려진 `tid`/`amount`/`ediDate`/`secret_key` 조합으로 직접 계산한 서명
   - Then: `verify_webhook_signature(body, signature)` → `True`
2. `test_verify_webhook_signature_tampered_body_returns_false`
   - Given: 서명은 그대로인데 `amount`만 바뀐 body
   - Then: `False`
3. `test_verify_webhook_signature_no_secret_key_returns_false`
4. `test_verify_webhook_signature_invalid_json_returns_false`

---

## Task 5 — `payment_router.py` 변경

**현재** (`app/payment/payment_router.py:72-94`):
```python
@router.post("/webhooks/toss", status_code=status.HTTP_200_OK, summary="토스 웹훅")
async def toss_webhook(
    request: Request,
    body: TossWebhookPayload,
    service: PaymentService = Depends(get_payment_service),
) -> dict[str, str]:
    raw_body = await request.body()
    signature = request.headers.get("TossPayments-Signature", "")
    if not service.verify_webhook(raw_body, signature):
        raise PaymentFailedError("웹훅 서명 검증 실패")
    await service.handle_webhook(body)
    return {"status": "ok"}
```

**목표 코드**:
```python
@router.post("/webhooks/nicepay", status_code=status.HTTP_200_OK, summary="나이스페이 웹훅")
async def nicepay_webhook(
    request: Request,
    body: NicePayWebhookPayload,
    service: PaymentService = Depends(get_payment_service),
) -> Response:
    """나이스페이 웹훅 수신 엔드포인트.

    나이스페이는 시그니처가 HTTP 헤더가 아니라 바디 안(`signature` 필드)에 있고,
    응답도 JSON이 아니라 body="OK" (text/html) 을 요구한다 — 토스와 다른 계약.
    """
    raw_body = await request.body()

    if not service.verify_webhook(raw_body, body.signature):
        raise PaymentFailedError("웹훅 서명 검증 실패")

    await service.handle_webhook(body)
    return Response(content="OK", media_type="text/html; charset=utf-8")
```

- [ ] 엔드포인트 경로 `/payments/webhooks/toss` → `/payments/webhooks/nicepay`.
      **주의**: 나이스페이 관리자 콘솔에 등록하는 웹훅 URL도 실 배포 도메인 기준으로
      같이 갱신해야 함(코드 밖 설정 — 체크리스트에만 남김, 실제 등록은 배포 시).
- [ ] 응답을 `dict[str, str]` → `Response(content="OK", media_type=...)`로 변경.
      FastAPI에서 `Response` 직접 반환 시 `response_model` 선언은 제거.
- [ ] `from fastapi import Response` import 추가.
- [ ] `PaymentService.verify_webhook`(`payment_service.py:170-172`)은 그대로 재사용
      가능(내부적으로 `self._gateway.verify_webhook_signature`로 위임만 하므로 변경 불필요).

**TDD** (`tests/integration/test_payment_router.py`, 신규 — 지금까지 payment_router
자체의 통합 테스트가 없었음, 이 기회에 추가):
1. `test_nicepay_webhook_valid_signature_returns_ok_body`
   - When: 올바른 서명으로 `POST /payments/webhooks/nicepay`
   - Then: HTTP 200, 응답 바디가 정확히 `"OK"` (JSON 아님)
2. `test_nicepay_webhook_invalid_signature_returns_422_or_400`
   - 기존 `PaymentFailedError` 매핑 그대로 검증

---

## Task 6 — `payment_service.py` 이벤트 상수/분기 재작성

**현재** (`app/payment/payment_service.py:23-27`, `174-229`):
```python
_EVENT_PAYMENT_STATUS_CHANGED = "PAYMENT_STATUS_CHANGED"
_TOSS_DONE = "DONE"
_TOSS_CANCELED = "CANCELED"
_TOSS_PARTIAL_CANCELED = "PARTIAL_CANCELED"
_TOSS_ABORTED = "ABORTED"

async def handle_webhook(self, payload: TossWebhookPayload) -> None:
    if payload.event_type != _EVENT_PAYMENT_STATUS_CHANGED:
        return
    data = payload.data
    pg_tid: str | None = data.get("paymentKey")
    ...
    pg_status: str = data.get("status", "")
    if pg_status == _TOSS_DONE: ...
    elif pg_status in (_TOSS_CANCELED, _TOSS_PARTIAL_CANCELED): ...
    elif pg_status == _TOSS_ABORTED: ...
```

**설계 결정**: 토스는 `eventType`으로 먼저 걸러야 했지만(웹훅이 결제 상태변경 말고도
다른 이벤트를 보낼 수 있는 구조), 나이스페이 웹훅은 애초에 결제 상태 변경 전용이라
`event_type` 체크 자체가 불필요 — 이 분기를 통째로 제거한다. 상태값 매핑은 아래처럼:

| 개념 | 토스 (`_TOSS_*`) | 나이스페이 (`status`) |
|---|---|---|
| 결제 완료 | `DONE` | `paid` |
| 전체 취소 | `CANCELED` | `cancelled` |
| 부분 취소 | `PARTIAL_CANCELED` | `partialCancelled` |
| 결제 거절/실패 | `ABORTED` | `failed` |
| (신규) 준비/대기 | 없음 | `ready`(가상계좌 발급 시) — 현재 로직엔 대응 분기 없음, 필요 여부 검토 |
| (신규) 만료 | 없음 | `expired`(가상계좌 입금기한 초과 추정) — 대응 분기 없음, 검토 필요 |

**목표 코드**:
```python
_NICEPAY_PAID = "paid"
_NICEPAY_CANCELLED = "cancelled"
_NICEPAY_PARTIAL_CANCELLED = "partialCancelled"
_NICEPAY_FAILED = "failed"

async def handle_webhook(self, payload: NicePayWebhookPayload) -> None:
    pg_tid = payload.tid
    if not pg_tid:
        return

    payment = await self._repo.get_by_pg_tid(pg_tid)
    if payment is None:
        payment = await self._repo.get_ready_payment_by_order_number(payload.order_id)
        if payment is None:
            return

    # Task 4(testcase2.md)의 결정 필요 사항과 동일 — PAID 이후에도 정상 CANCELLED
    # 이벤트는 통과시켜야 함. NICEPAY 버전으로 그대로 이식.
    if payment.status == PaymentStatus.PAID:
        if payload.status == _NICEPAY_PAID:
            return
        if payload.status not in (_NICEPAY_CANCELLED, _NICEPAY_PARTIAL_CANCELLED):
            return  # 그 외(failed 등)가 PAID 이후 오는 비정상 케이스 — 무시

    if payload.status == _NICEPAY_PAID:
        payment.status = PaymentStatus.PAID
        payment.pg_tid = payment.pg_tid or pg_tid
        order = await self._repo.get_order_by_id(payment.order_id)
        if order is not None and order.status == OrderStatus.PENDING:
            await self._repo.update_order_paid(order)
    elif payload.status in (_NICEPAY_CANCELLED, _NICEPAY_PARTIAL_CANCELLED):
        payment.status = PaymentStatus.CANCELLED
        if payload.status == _NICEPAY_CANCELLED:
            await self._restore_order_stock_and_cancel(payment.order_id)
    elif payload.status == _NICEPAY_FAILED:
        payment.status = PaymentStatus.FAILED
        await self._restore_order_stock_and_cancel(payment.order_id)
```

- [ ] 위 상수/분기 교체. **`_restore_order_stock_and_cancel` 내부 로직은 PG 무관이라
      그대로 재사용**(변경 불필요).
- [ ] `payload.data.get("failure", {}).get("message")`로 `fail_reason`을 채우던 로직 —
      나이스페이 `resultMsg`를 대신 사용:
      `payment.fail_reason = payload.result_msg`
- [ ] **`testcase2.md` Task 3(웹훅 락)/Task 4(PAID 이후 CANCELED 통과)가 이미
      적용됐다면 그 로직 그대로 이식**(위 목표 코드에 이미 Task 4 결정사항 반영해둠).
      아직 적용 안 됐다면 이 Task와 동시에 락까지 같이 넣는 게 효율적 — Task 0-1의
      순서 결정에 따라 조정.
- [ ] `ready`/`expired` 상태 처리 분기 추가 여부 결정 — 가상계좌를 결제수단으로
      노출할 계획이 있으면 필요(가상계좌 발급 시 `ready` 웹훅이 먼저 오고, 실제
      입금 시 `paid` 웹훅이 다시 옴 — 지금 코드는 `ready`를 완전히 무시하는데 이게
      맞는 동작인지 확인). 카드 결제만 쓸 거면 스킵해도 무방.

**TDD** (`tests/test_payment_service.py` — 기존 웹훅 테스트 전체를 나이스페이 필드로
재작성, 테스트 이름은 그대로 유지 가능):
1. `test_webhook_paid_transitions_order_to_paid` (기존 `test_webhook_done_transitions_order_to_paid` 대체)
2. `test_webhook_cancelled_cancels_order_and_restores_stock`
3. `test_webhook_partial_cancelled_does_not_restore_stock`
4. `test_webhook_failed_cancels_order_and_restores_stock`
5. `test_webhook_idempotent_already_paid`
6. `test_webhook_cancelled_after_paid_restores_stock` (`testcase2.md` Task 4 이식)
7. `test_webhook_arrives_before_confirm_finds_payment_by_order_id_fallback`

(전부 `docs/testcase.md`/`docs/testcase2.md`에 이미 있던 테스트를 필드명만 나이스페이로
바꾼 것 — **새로 설계할 필요 없이 기계적으로 이식** 가능한 부분이 대부분.)

---

## Task 7 — 모델 enum 정리

**현재** (`app/payment/models.py:17-31`):
```python
class PgProvider(enum.StrEnum):
    """결제 PG. MVP 는 TOSS 단일 계약."""
    TOSS = "TOSS"
    KAKAO = "KAKAO"
    NAVER = "NAVER"

class PaymentMethod(enum.StrEnum):
    CARD = "CARD"
    BANK = "BANK"
    KAKAO_PAY = "KAKAO_PAY"
    NAVER_PAY = "NAVER_PAY"
    TOSS_PAY = "TOSS_PAY"
```

**목표**:
```python
class PgProvider(enum.StrEnum):
    """결제 PG. MVP 는 NICEPAY 단일 계약."""
    NICEPAY = "NICEPAY"

class PaymentMethod(enum.StrEnum):
    CARD = "CARD"
    BANK = "BANK"
    KAKAO_PAY = "KAKAO_PAY"
    NAVER_PAY = "NAVER_PAY"
    SAMSUNG_PAY = "SAMSUNG_PAY"  # Task 0-4 결정에 따라 TOSS_PAY 대체 또는 추가
```

- [ ] `PgProvider`에서 `TOSS`/`KAKAO`/`NAVER` 제거, `NICEPAY` 추가.
      **DB 마이그레이션 불필요** — 컬럼이 `Enum(PgProvider, native_enum=False, length=20)`,
      즉 Postgres 네이티브 ENUM이 아니라 `VARCHAR(20)` + 애플리케이션 레벨 검증이라
      Alembic revision 없이 Python enum만 바꾸면 됨(`payment/models.py` 주석에도
      이미 명시돼 있는 설계). 단, 기존 행에 `'TOSS'` 문자열이 남아있다면 그 값을 읽을 때
      Python enum 매칭 실패(`ValueError`)가 날 수 있으니 **운영 데이터가 있다면 Task 0-5
      결정에 따라 처리**(테스트 환경이면 그냥 시드 재생성).
- [ ] `PaymentMethod.TOSS_PAY` 처리는 Task 0-4 결정 결과를 따름.
- [ ] `Payment.pg_provider` 저장 시점(현재 `payment_service.py::init_payment`에서
      `pg_provider=PgProvider.TOSS` 하드코딩된 부분, `payment_service.py:73`) →
      `PgProvider.NICEPAY`로 교체.

**TDD**: enum 값 교체는 기존 테스트의 fixture(`make_payment` 등에서 `PgProvider.TOSS`
쓰던 부분)를 `PgProvider.NICEPAY`로 일괄 치환하면 됨 — 새 테스트 불필요, 회귀로 충분.

---

## Task 8 — `FakePaymentGateway` 정합성 확인

**현재** (`app/payment/adapters/fake.py`) — `TossConfirmResult` 반환.

- [ ] `TossConfirmResult` → `PgConfirmResult`(Task 2 리네임) 참조만 갱신. **로직
      자체는 PG 무관이라 변경 불필요** — 이게 애초에 Protocol 기반 설계를 한 이유
      (`ports.py` 파일 docstring: "구체 PG 구현체는 갈아끼울 수 있다").
- [ ] `card_company="개발카드"` 등 필드 값 자체는 나이스페이든 토스든 상관없는
      더미값이라 그대로 둬도 무방. 원하면 `"NICEPAY-FAKE"`처럼 더 명확하게 바꿔도 됨
      (선택 사항, 필수 아님).

**TDD**: 없음 — Task 2의 이름 변경 회귀로 커버됨.

---

## Task 9 — 취소(cancel) API 신규 연동 여부 결정

**현재 상태**: `OrderService.cancel_order`/`request_refund`는 DB 상태 전환만 하고
PG 취소 API를 호출하지 않는다(`testcase.md` Task 1-2에 "PG 환불은 payment 모듈 책임,
이 문서 범위 밖"이라 명시돼 있고 여태 미구현 상태로 남아있음).

- [ ] **결정**: 이번 마이그레이션에서 실제 PG 취소 연동까지 할지, 계속 범위 밖으로
      둘지. 아래 두 옵션:
      - (a) **범위 밖 유지(권장, MVP)**: 지금처럼 DB 상태만 바꾸고 실제 환불은 나이스페이
        관리자 콘솔에서 수동 처리. 이 Task는 스킵.
      - (b) **자동 연동**: `PaymentRepository`/`PaymentService`에 `cancel_payment`
        추가, `1-5절`의 취소 API를 호출하는 어댑터 메서드(`PaymentGateway.cancel(...)`)를
        Protocol에 새로 추가. **Protocol 확장이라 `FakePaymentGateway`도 같이
        구현해야 함**(안 하면 Protocol 정합성 체크 `_: PaymentGateway = FakePaymentGateway()`가
        타입체크에서 깨짐 — `fake.py` 맨 아래 이미 있는 이 런타임 체크 패턴 유지).
- [ ] (b) 선택 시 TDD 설계는 이 문서 범위를 넘어서므로 별도 `docs/testcase4.md`
      (또는 이 문서에 이어 붙이기)로 분리 — **이번 마이그레이션 완료 조건에는
      포함시키지 않는다.**

---

## Task 10 — 프론트 연동 계약 변경 (`returnUrl` 아키텍처)

**문제**: 1-2절에서 확인했듯 나이스페이는 인증 완료 시 `returnUrl`로 **브라우저가
form POST를 직접 전송**한다. 토스는 프론트가 리다이렉트 쿼리스트링을 받아서 fetch로
`/payments/confirm`을 호출하는 구조였는데, 나이스페이는 이 패턴이 그대로 안 맞는다.

**설계 결정 필요**:

- [ ] **옵션 A**: `returnUrl`을 **백엔드 엔드포인트**(`POST /payments/nicepay-return`
      같은)로 직접 등록. 이 엔드포인트가:
      1. `authToken`+`clientId`+`amount`로 `signature` 검증(1-2절 계산식)
      2. 검증 통과 시 그 자리에서 바로 승인 API(`confirm`) 호출까지 수행하거나,
      3. 프론트 성공 페이지로 302 리다이렉트(쿼리스트링에 `order_number` 정도만 실어서)
      - 장점: 브라우저 POST를 정상적으로 받을 수 있는 유일하게 확실한 방법
      - 단점: 지금의 `POST /payments/confirm`(사용자 인증 필요, `get_active_user`
        의존)과 별개로 **인증 없는** 엔드포인트가 하나 더 생김 — `authToken`/
        `signature` 검증이 사실상의 인증 역할을 대신해야 함(웹훅 엔드포인트와
        비슷한 신뢰 모델).
- [ ] **옵션 B**: `returnUrl`을 프론트 URL로 두되, 프론트 서버(Next.js 등)가 자체
      라우트에서 이 POST를 받아 파싱한 뒤 클라이언트 사이드로 값을 넘기고, 거기서
      기존처럼 우리 `/payments/confirm`을 호출. **프론트 아키텍처에 달림 — 백엔드
      작업 범위 밖**, 프론트 담당자와 협의 필요.
- [ ] 어느 쪽이든 **`PaymentConfirmRequest`의 필드명 자체는 유지 가능**
      (`payment_key`=`tid`, `order_id`=`orderId`, `amount`) — 프론트가 어디서 이
      값을 얻어오는지(백엔드 리다이렉트 vs 자체 파싱)만 달라짐. 이 스키마는 안
      바꿔도 되는 게 다행인 지점.

**이 Task는 프론트/인프라 결정이 선행돼야 커밋 가능** — 백엔드 코드 변경은 옵션
확정 후 별도 서브 Task로 구체화.

---

## Task 11 — 기존 테스트 전수 이관

| 기존 파일 | 처리 |
|---|---|
| `tests/test_toss_adapter.py` | 삭제, `tests/test_nicepay_adapter.py`로 대체 (Task 3 TDD 참고) |
| `tests/test_payment_service.py` | 웹훅 관련 테스트 전부 필드명 교체 (Task 6 TDD 참고), `init_payment`/`confirm_payment` 관련 테스트는 `PgProvider`/`PgConfirmResult` 이름만 교체하면 그대로 유효 |
| `tests/integration/test_payment_service.py` (있다면, `testcase2.md` Task 5) | 동일 원칙 |
| `tests/integration/test_payment_router.py` (신규, Task 5) | 새로 작성 |

- [ ] `.venv/bin/pytest -v` 전체 그린 확인
- [ ] `.venv/bin/ruff check app tests` 클린 확인
- [ ] `.venv/bin/mypy app` 클린 확인 (CLAUDE.md 게이트 3종 — 이 마이그레이션도 예외 없음)
- [ ] 커버리지 확인: `.venv/bin/pytest --cov=app --cov-report=term-missing` — 변경된
      파일(`payment/` 하위 전체) 라인 커버리지 ≥ 80%

---

## Task 12 — `testcase.md` / `testcase2.md` 관계 정리

- [ ] 이 마이그레이션 완료 후, `testcase2.md`에 아직 체크 안 된 Task가 남아있다면
      그 문서의 코드 스니펫("현재 코드"/"목표 코드")이 전부 토스 기준이라 **더 이상
      그대로 못 씀** — 이 문서 Task 6에서 이미 이식해둔 부분(웹훅 락 + PAID 이후
      CANCELED 통과)을 제외한 나머지(Task 1 사용자취소 락, Task 2 만료처리 락,
      Task 5 검증테스트)는 PG와 무관한 `OrderService`/`init_payment`/`confirm_payment`
      로직이라 **그대로 유효** — `testcase2.md`는 별도로 계속 진행하면 됨, 폐기하지 않음.
- [ ] `testcase2.md` 상단에 "이 문서의 웹훅 관련 Task(3, 4)는 `nicepay_migration.md`
      Task 6에 흡수/이식됨" 같은 안내 한 줄 추가해서 나중에 헷갈리지 않게 할 것.
- [ ] `scripts/run_testcase2_loop.sh`를 이 문서(`nicepay_migration.md`)에도 재사용할지,
      별도 루프 스크립트(`run_nicepay_migration_loop.sh`)를 새로 만들지는 사용자
      선택 — 스크립트 자체는 `docs/testcase2.md` 경로가 하드코딩돼 있어(`DOC="$REPO_DIR/docs/testcase2.md"`)
      그대로는 이 문서를 못 처리함. 필요하면 `DOC` 인자를 받도록 스크립트를
      일반화하거나 복제해서 경로만 바꾼 새 스크립트를 만들 것.

---

## 세션 재개 체크리스트

1. Task 0의 결정사항이 전부 확정됐는지 먼저 확인 — 결정 안 된 상태로 Task 1 이후
   진행하면 나중에 되돌리는 비용이 큼.
2. `git status`/`git log`로 실제 코드 상태 우선 신뢰 (문서 체크박스보다 코드가 진실).
3. 나이스페이 API 스펙은 이 문서에 정리해뒀지만 **실제 계약/샌드박스 키 발급 전까지는
   미검증** — "⚠️ 확인 필요"라고 표시한 항목(카드 마스킹 포맷, 승인번호 필드,
   웹훅 `ediDate` 포함 여부)은 실제 응답을 받아보기 전엔 목표 코드가 틀릴 수 있다는
   전제로 접근할 것.
4. CLAUDE.md 게이트(`pytest`/`ruff check app tests`/`mypy app`) 통과 없이 다음 Task로
   넘어가지 않는다.
5. 커밋/푸시는 사용자가 명시적으로 요청할 때만.
