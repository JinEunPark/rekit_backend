# Rekle Backend TODO — 디자인 시스템 기반 구현 계획

## 후속 조치 (2026-08-14 세션 정리)

> Octomo 휴대폰 인증 마이그레이션 + 전화번호 010-0000-0000 정규화 + 재고 SOLD_OUT
> 자동전환 작업 완료 후 사용자가 직접 처리해야 할 항목. 완료하면 체크.

- [x] **[보안/긴급] Octomo API 키 재발급** (2026-11-05 사용자 확인 완료) — 작업 중 로컬 `.claude/settings.json`에
      평문으로 남아있던 게 발견됨(`89068e69...`). git 히스토리엔 안 올라갔지만
      `.env`에 저장된 현재 활성 키와 동일한 값이라, Octomo 콘솔
      (https://octomo.octoverse.kr) 에서 재발급 후 `.env` 교체 권장.
- [ ] **[결제] 토스페이먼츠 실연동** — 전체 이해: **[docs/payment_dev_state.md](payment_dev_state.md)** ·
      작업 가이드: **[docs/toss_integration.md](toss_integration.md)** (Task 1~8, 왜→뭘바꾸나→검증→완료 4단)
      - ✅ **Task 1·2 완료 (2026-08-31, 커밋 `233a264`)** — 웹훅 검증을 "조회 재확인" 방식으로 교체
        (`verify_webhook_signature` 제거 → `gateway.get_payment()`), 웹훅 status 8종 처리 +
        `EXPIRED` 추가, 부분취소 `PARTIAL_CANCELLED` 정정
      - ✅ **Task 3·4 완료 (2026-09-04, 커밋 `636f00f`)** — `TossPaymentGateway.cancel()`
        (`POST /v1/payments/{paymentKey}/cancel`, `Idempotency-Key`, `{code,message}` 파싱) +
        `PaymentService.cancel_payment()` + repo `update_status_cancelled` +
        `order_service.cancel_order`/`request_refund`·`admin_order_service.cancel_order` 가
        PAID/PREPARING 이면 PG 취소 먼저 호출(실패 시 롤백), PENDING 은 스킵. deps 와이어링.
        503 passed / ruff 0 / mypy 0
      - ✅ **Fake 게이트웨이 제거 (2026-09-04, 커밋 `282c34c`)** — `use_fake_pg` 토글 삭제, 항상 실제 토스
      - ✅ **결정**: clientKey 는 프론트 env(`VITE_TOSS_CLIENT_KEY`)로 — 백엔드 `toss_client_key` 불필요
      - ✅ **키 반영 (2026-09-04)**: 본인 계정 테스트 키 `.env` 세팅 (`TOSS_SECRET_KEY=test_gsk_GePWvyJ…`),
        프론트 `.env.local` `VITE_TOSS_CLIENT_KEY=test_gck_GjLJoQ…`. 둘 다 gitignore
      - ✅ **Task 5 완료 (2026-10-02 확인, 커밋 `8d5fbd4`)** — confirm 하드닝. 코드 확인 완료:
        `adapters/toss.py:81` `Idempotency-Key: confirm-{payment_key}`, `:96` 4xx → `_raise_toss_failure()`,
        `payment_service.py:159` `fail_reason` 저장 + FAILED 전이
      - [ ] **Task 6 — 정리 (2건, 서로 독립)**
        - [ ] `app/payment/ports.py` 삭제 — dead code. 2026-10-02 확인: 레포 전체에서 참조 **0건**
              (`grep -rn "payment.ports" app/ tests/`). 혼동 주의 — 실제로 쓰이는 Protocol 은
              `app/payment/adapters/ports.py` 이고 **이건 지우면 안 된다**. 지운 뒤 `pytest`·`mypy app` 로 확인
        - [ ] 백엔드 `docs/api.md` §10.1/§10.2 를 실제 구현에 맞게 갱신. 현재 문서가 틀린 부분:
              엔드포인트 `/payments/verify` → **`/payments/confirm`**,
              응답의 `data` envelope → **없음(평평한 객체)**, 주문 상태 `PENDING_PAYMENT` → **`PENDING`**.
              실제 스키마는 `app/payment/payment_schemas.py` 가 정답 —
              init 요청 `{order_number, method}` / 응답 `{payment_id, order_number, amount, customer_name}`,
              confirm 요청 `{payment_key, order_id, amount}`(`order_id` 는 order_number 문자열 — 토스가 orderId 로 부름) /
              응답 `{order_number, status, paid_at, card_company, card_last4, installment_months}`
      - ✅ **결정 (2026-09-04): 가상계좌 안 함** — `confirm` 이 토스 `status != "DONE"` 거절
        (입금 전 주문 확정 방지). 실시간 계좌이체(BANK, 즉시 DONE)는 그대로 사용 가능
      - [ ] **부분취소 재고 정책** — `cancel_amount` 경로는 어댑터·서비스에 있으나 order/admin 은 전액만 호출.
        부분취소 시 라인별 재고 복구 정책 미정
      - [x] **방치된 PENDING 주문 정리 — 결제창 이탈/재시도 전 경우 대응 (2026-10-16 완료, 운영 수동 검증 남음)**
        - 현상: 주문 생성 시 재고를 먼저 깎는다. 결제창을 닫거나 탭을 닫으면 주문은 `PENDING` + 재고 차감 상태로
          남고, 다시 결제하면 상품이 `SOLD_OUT` 이라 `ProductUnavailableError`("현재 주문할 수 없는 상품").
          기존 만료(`_expire_if_abandoned`)는 `get_order()` 에서만 돌아 사실상 정리되지 않았다.
        - **원칙: 결제 여부가 불확실하면 취소하지 않는다** — READY 결제가 있으면 토스에 orderId 로 실상태를 조회한 뒤
          정리. 최악이어도 "재고가 잠시 묶임" 이지 "돈 빠졌는데 주문 취소" 는 만들지 않는다.
        - [x] **1. confirm 동시성 버그** — `confirm_payment` 가 주문을 락 없이 읽어서, 취소/만료와 동시에 돌면
              토스 승인 성공 + 재고 복구 + `PAID` 덮어쓰기(이중 판매) 가능. 주문 `FOR UPDATE` 로 조회
        - [x] **2. 안전 정리 함수** — 토스 어댑터 `get_payment_by_order_id` (`GET /v1/payments/orders/{orderId}`) +
              `PaymentService.release_pending_order()`: READY 없음 → 취소 / 토스 404·ABORTED·EXPIRED·READY·IN_PROGRESS →
              취소 / DONE → 결제 완료 처리 / 조회 실패 → skip
        - [x] **3. 호출 지점 연결** — `create_order` 시작 시 같은 사용자의 PENDING 주문 정리(재시도 즉시 통과),
              `_expire_if_abandoned` 도 공통 함수 사용
        - [x] **4. 취소된 주문에 웹훅 DONE** — 자동 PG 취소(환불) + error 로그
        - [x] **5. 스케줄러** — lifespan asyncio 태스크, 주기적으로 30분 지난 PENDING 을 `FOR UPDATE SKIP LOCKED`
              로 가져와 정리 (gunicorn 멀티 워커 중복 실행 안전)
        - [x] **6. 프론트** — `PaymentFailView`·`pay()` catch 에서 `orders.cancel` 조용히 호출(즉시 재고 반납),
              `PaymentReturnView` confirm 네트워크 오류/502 시 confirm 재시도(멱등) → 그래도 불명이면 주문 상태로 판단
        - 구현 위치: `payment_service.release_pending_order` / `_refund_late_approval`,
          `order_service.create_order`·`_release_pending`, `order/abandoned_order_sweeper.py`(lifespan 에서 시작),
          `adapters/toss.get_payment_by_order_id`, 설정 `PENDING_ORDER_SWEEP_INTERVAL_SECONDS`(기본 120, 0=끔)
        - 덤으로 고친 것: `PaymentRepository` 락 조회에 `populate_existing` 누락(같은 세션에서 먼저 읽은 주문의
          낡은 status 로 더블체크하던 문제), 웹훅 락 순서를 주문 → 결제로 통일(confirm 과 데드락 방지)
        - [x] **수동 검증 (스테이징)** (2026-11-05 사용자 확인 완료): ① 결제창 닫기 → 즉시 다른 결제수단으로 재결제 성공
              ② 결제창 닫고 탭 종료 → 30분+2분 뒤 상품 재고 복구 확인(상세 안 열고)
              ③ 운영 로그에 "취소된 주문의 결제 승인 감지" error 가 뜨면 토스 개발자센터에서 환불 확인
      - [ ] **운영 — 실키 전환 (오픈 직전, 전자결제 심사 완료 후)** : `TOSS_SECRET_KEY` 를 `test_gsk_*` →
        `live_gsk_*` 로 교체(운영 시크릿 `~/rekit/secrets/rekit_backend.env`), 프론트 `VITE_TOSS_CLIENT_KEY` 도
        같은 상점의 `live_gck_*` 로 **동시에** 교체해야 한다(한쪽만 바꾸면 `INVALID_API_KEY`).
        웹훅 URL·결제창 허용 도메인 등록은 2026-09-04 완료됨(아래 수동 테스트 preamble 참고)
      - ✅ **프론트 위젯 연동 완료** — `rekle` 레포에 `src/api/payments.ts`, `src/config/payments.ts`,
        `src/composables/usePaymentHandoff.ts`, `src/views/checkout/PaymentReturnView.vue`·`PaymentFailView.vue` 구현됨.
        남은 프론트 잔여 항목은 `rekle/todo.md` 의 "P1 — 결제" 참고

### [결제] 내가 직접 해봐야 할 수동 테스트 (2026-09-05, 운영/스테이징 배포 후) — ✅ 2026-11-05 A~F 전부 완료 (사용자 확인)

> 자동 테스트로 못 잡는 것 = 실제 토스 API 호출·웹훅·프론트 위젯 결합. 개발자센터 결제내역이 최종 증거.
>
> **(2026-10-02 당시 기록 — 이후 배포·수동 테스트 완료. 아래는 이력으로 보존)**
> 결제 하드닝 커밋들(`4d23e7c` 웹훅 금액검증·`636f00f` 취소/환불·`8d5fbd4` confirm 하드닝)은 master 에
> 올라가 있지만 **운영에 배포된 적이 없다**. 운영은 태그 `0.0.2`(= "롤백 테스트용 빈 릴리스" 커밋) 기준 이미지로
> 떠 있었다. 2026-10-02 에 태그 `0.0.3` 을 푸시했고, 이 태그를 Jenkins `build-was` → `deploy-was` 로 올리면
> 위 결제 커밋들이 **한꺼번에** 운영에 나간다. 그러니 아래 체크리스트는 `0.0.3` 배포 직후에 수행할 것.
> (배포 여부 확인법: `curl -s https://rekit.co.kr/api/v1/categories | head -c 120` 에 `image_url` 필드가
> 보이면 0.0.3 이상이 떠 있는 것.)
>
> 사전: 프론트 위젯 연동 완료 · 아래 등록 항목 전부 완료(2026-09-04)
>   - ✅ 개발자센터 웹훅 URL `https://{도메인}/api/v1/payments/webhooks/toss` 등록 (`PAYMENT_STATUS_CHANGED`)
>   - ✅ 결제창 허용 도메인 등록
>   - ✅ 엣지 nginx 웹훅 경로 인증 없이 통과

**A. 배포/설정 스모크 (가장 먼저)**
- [x] 배포 후 앱이 정상 부팅됐는지 — `TOSS_SECRET_KEY` 가 `config.py` 에서 **필수값**이 됐으므로,
      운영 시크릿(`~/rekit/secrets/rekit_backend.env`)에 없으면 부팅 자체가 실패한다. 헬스체크 200 확인
- [x] `GET /api/v1/...` 아무 인증 불필요 엔드포인트로 서버 살아있는지 + 로그에 설정 에러 없는지
- [x] (스테이징이면) 스테이징 개발자센터에도 웹훅 URL·허용 도메인 각각 등록됐는지 (MID 별로 따로)

**B. 결제 해피 패스 (카드)**
- [x] 주문서 → 결제 → `/payments/init` 201, 토스 위젯 뜸 (본인 `test_gck_*`)
- [x] 토스 테스트 카드로 승인 → successUrl 리다이렉트 (`?paymentKey&orderId&amount`)
- [x] `/payments/confirm` 200 → `payments` 행 `PAID` + 카드메타(`card_company`/`card_last4`) 채워짐, `orders` `PAID`
- [x] **개발자센터 결제내역에 "승인" 1건** (본인 상점 장부에 찍히는지 = 본인 키 정상 증거)
- [x] 결제완료 이메일 수신
- [x] 재고: 주문 시 차감 → 결제 성공 후 그대로 유지

**C. 결제 실패/멱등**
- [x] 위젯에서 취소(뒤로가기) → failUrl 페이지, 주문은 `PENDING` 유지 (30분 후 자동 만료 취소)
- [x] `confirm` 에 틀린 `amount` → `PAYMENT_FAILED`(422) "금액 불일치"
- [x] 같은 주문에 `confirm` 두 번 → 두 번째도 200(멱등), 토스 승인 1건만
- [x] 가상계좌를 (혹시 위젯에서 고를 수 있으면) 선택 → `confirm` 이 "DONE 이 아님"으로 422 거절

**D. 주문 취소 → PG 환불 (Task 3·4 핵심 검증)**
- [x] `PAID` 주문 `POST /api/v1/orders/{order_number}/cancel` → 200, `payments` `CANCELLED`, `orders` `CANCELLED`, 재고 복구(+수량)
- [x] **개발자센터 결제내역에 "취소" 표시** + `cancels[]` 에 전액
- [x] 같은 주문 다시 `cancel` → `ORDER_CANCEL_FORBIDDEN` (이미 취소, 토스 재호출 없음)
- [x] `PENDING` 주문(결제 전) `cancel` → 200, 토스 호출 없이 `CANCELLED` (개발자센터에 아무것도 안 뜸)
- [x] 관리자 `POST /api/v1/admin/orders/{order_number}/cancel` (`{"reason":"..."}`) → 동일 + 토스 취소 사유에 reason 전달됐는지
- [x] `DELIVERED` 주문 `POST /api/v1/orders/{order_number}/refund/request` → `REFUNDED` + 토스 취소. 재고는 복구 안 됨(정상)
- [x] (선택) 토스가 취소 거절하는 상황 재현(예: 이미 콘솔에서 수동취소한 결제를 우리가 cancel) → 422, **주문 상태가 롤백되어 그대로인지** (전환 안 됨 확인)

**E. 웹훅 (Task 1·2 + 2026-09-04 하드닝 핵심 검증)**
- [x] 결제하면 서버 로그에 `"event": "토스 웹훅 수신"` + `"event_type": "PAYMENT_STATUS_CHANGED"`, `"remote_status": "DONE"` 뜨는지
      (2026-11-05 구조화 로그로 형식 변경 — `docker logs rekle-app | grep "토스 웹훅 수신"`)
      (이미 confirm 으로 PAID 면 멱등 무시 — 로그는 뜨되 상태 변경 없음)
- [x] 개발자센터 → 해당 웹훅 상세 → **전송 기록이 "성공"(200)** 인지 (실패면 URL/nginx/방화벽 점검)
- [x] **⭐ confirm 유실 시나리오** — 결제창 인증까지 끝내고 successUrl 리다이렉트 직전에 **브라우저/탭 강제 종료**
      (`/payments/confirm` 이 호출 안 되게). 몇 초~수십 초 후:
      `payments` 행이 웹훅만으로 `PAID` + `orders` `PAID` 로 전환됐는지 + 카드메타 채워졌는지.
      → **이게 웹훅의 존재 이유. 반드시 통과해야 함**
- [x] 위 시나리오 후 로그에 `웹훅 DONE 금액 불일치` 에러가 **없어야** 함 (있으면 `totalAmount` 파싱/금액 산정 버그)
- [x] **개발자센터에서 결제를 수동 취소** → `CANCELED` 웹훅 도착 → 우리 `payments` `CANCELLED` + `orders` `CANCELLED` + 재고 복구 자동으로 되는지 (조회 재확인 방식 동작 증거)
- [x] 개발자센터 웹훅 "재전송" → 멱등 (이중 재고 복구/상태 재전환 없음, 로그만 다시 뜸)
- [x] 백엔드를 잠깐 껐다 켠 상태에서 웹훅 도착 → 토스가 재시도(최대 7회)해서 결국 처리되는지 (5xx→재시도)
- [x] 응답 시간 — 웹훅 처리가 10초 이내 200 인지 (초과 시 토스가 실패로 간주·재시도). `get_payment` 지연 시 위험

**F. 결과 기록**
- [x] 통과/실패를 이 목록에 체크, 실패 케이스는 별도 이슈로
- [x] **[DB] Alembic 마이그레이션 배포 반영** (수동 실행 불필요 — 운영 compose 가 기동 시 `alembic upgrade head` 자동 실행, `6105137b8e93` 은 태그 0.0.4 에 포함) — `6105137b8e93`(CI/DI 제거 →
      Octomo 전화인증 대체)가 로컬 dev DB엔 이미 적용돼 있음(`alembic current`
      == head). staging/production 에는 아직 미적용 — 배포 전
      `.venv/bin/alembic upgrade head` 실행 필요.
- [x] **[데이터] 기존 전화번호 백필** — `alembic/versions/ea245030888c_...py`
      (data-only, 스키마 변경 없음)로 `users.phone`/`addresses.phone`/
      `orders.recipient_phone` 세 컬럼을 `app/core/phone.py::normalize_phone`
      규칙(`01[016789]` + 7~8자리 → `010-0000-0000`/`011-000-0000`)과 동일하게
      SQL 정규식으로 백필. 로컬 dev DB 적용 완료(users 3건/addresses 7건/
      orders 12건 재포맷 확인), downgrade(하이픈 제거) 왕복 검증 완료.
      staging/production 배포 시 `alembic upgrade head` 필요.
- [x] **[검증] Octomo 인증 플로우 실사용 확인** (2026-11-05 사용자 확인 완료) — 이번 세션에서 발견한 버그
      2건(QR 발급/exists 조회가 200 아닌 201 반환, 성공 후 Redis 키 삭제 안 되던
      것)이 전부 "실제 키로 붙여봐야 드러나는" 종류였음. 실 API 키로 QR
      발급→스캔→전송까지 한 번 더 end-to-end 확인 권장.
- **[참고·작업 규칙] 세션 간 작업 충돌 주의** — 이번 세션 도중 다른 세션이 동시에
      같은 파일(`app/payment/adapters/ports.py`)을 건드려, NicePay 전환 준비로
      클래스명만 바꾸고 나머지 파일은 그대로 둔 채(임포트 에러 유발) 남겨둔
      적이 있었음(현재는 원복 완료). 여러 세션을 동시에 돌릴 땐 자주
      커밋/푸시하고, 새 세션 시작 전 `git pull`로 동기화 권장.

---

## 관측성(로깅·메트릭·모니터링) 구축 + 부하테스트 개선 루프 (2026-11-05 계획)

> **목표**: "장애를 사용자 문의로 먼저 알게 되는" 상황 제거 → 부하테스트로 병목을 숫자로 찾고 개선하는 루프 확립.
> **진행 순서**: O0(선결 버그) → O1(로깅) → O2(메트릭) → O3(에러 추적) → O4(헬스체크) → O5(모니터링 스택)
> → O6(알림) → O7(부하테스트) → O8(개선 루프). 각 단계는 TDD(Red→Green→Refactor) + 완료 게이트
> (`pytest -v` / `ruff check app tests` / `mypy app` 전부 0건) 통과 후 체크.
> **원칙**: 라벨/메트릭에 `user_id`·`order_number` 등 고유값 금지(→ 로그로) · 모든 시간 UTC · 운영에서 부하테스트 금지.

### O0. 선결 — 현재 이미 유실 중인 것 (가장 먼저)

- [x] **(2026-11-05 완료 — O1-1)** **로깅 미설정으로 INFO 로그 전부 유실** — 앱 어디에도 `basicConfig`/`dictConfig` 없음 → root 로거
      `WARNING`·핸들러 0개 (2026-11-05 확인). gunicorn 은 `gunicorn.*` 로거만 설정. 그 결과
      `payment_service.py` 의 `"토스 웹훅 수신 — ..."` / 결제 확정 INFO, 스위퍼 `"방치 주문 N건 정리"` 가
      운영에서 안 찍힘 → 위 [결제] 수동 테스트 체크리스트의 "로그에 ~ 뜨는지" 항목 검증 불가. **O1-1 로 해결**
- [x] **(2026-11-05 완료)** **컨테이너 로그 로테이션 없음** — `docker-compose.prod.yml` 에 `logging:` 옵션 없음 → json-file 무제한 →
      디스크 고갈 위험. app/postgres/redis 전부에
      `logging: {driver: json-file, options: {max-size: "20m", max-file: "5"}}` 추가
      → `x-logging` anchor 로 1회 정의 후 3개 서비스 참조. **운영 반영은 `docker compose up -d` 로 컨테이너 재생성 필요**
      (logging 옵션은 재시작만으론 안 바뀜 — postgres/redis 포함)
- [x] **(2026-11-05 완료)** **`uvicorn.workers.UvicornWorker` deprecated** (uvicorn 0.46.0 에서 경고 확인) — `uvicorn-worker` 패키지 추가 +
      `-k uvicorn_worker.UvicornWorker` 로 교체. `docker-compose.prod.yml` `command` 와 `Dockerfile` `CMD` 둘 다
      (+ `docs/요구사항정의서.md` 권장 명령 갱신). 로컬 gunicorn -w 2 기동·요청·종료 확인

### O1. 구조화 로깅 (structlog — 의존성에만 있고 미사용 상태)

- [x] **O1-1 로깅 초기화 (2026-11-05 완료)** — `app/core/logging.py` 신규 `configure_logging()`
  - 테스트 `tests/test_logging.py` 12건. 로컬 gunicorn(APP_ENV=production) 으로 uvicorn·액세스·SQL 로그 JSON 출력 확인
  - 부수 수정: `database.py` `echo=settings.debug` 제거 → DEBUG 시 `sqlalchemy.engine` 레벨만 INFO
    (echo 는 자체 핸들러를 달아 root 핸들러와 SQL 이중 출력)
  - ~~남은 것: gunicorn master 로그 포맷~~ → 2026-11-05 해결 (아래 "O1 남은 한계" 참고)
  - structlog + 표준 `logging` 통합 (`ProcessorFormatter`) — 기존 `logging.getLogger(__name__)` 호출부 수정 없이 JSON 출력
  - 운영(`APP_ENV=production`): JSON 한 줄 / 로컬: 컬러 콘솔
  - `LOG_LEVEL` 환경변수 (default `INFO`) — `config.py` · `.env.example` · `.env` 3곳 동시 수정
  - `timestamp` 는 UTC ISO-8601 (`TimeStamper(fmt="iso", utc=True)`)
  - uvicorn/gunicorn 로거도 같은 포맷으로 (중복 출력 방지: `propagate` 정리)
  - `create_app()` 초입에서 호출
  - 테스트: 설정 후 INFO 로그가 출력되는지 / JSON 파싱 가능한지 / 레벨 env 반영되는지
- [x] **O1-2 Request ID (상관 ID) (2026-11-05 완료)** — `app/core/middleware.py` `RequestContextMiddleware` (순수 ASGI)
  - 요청 헤더 `X-Request-ID` 가 `^[A-Za-z0-9._-]{1,128}$` 면 이어받고, 아니면(공백·개행·초과길이·빈값) UUID4 생성
  - `bind_contextvars(request_id=...)` → 그 요청의 모든 로그(SQL 로그 포함)에 자동 포함 (Spring MDC 대응)
  - 응답 헤더 `X-Request-ID` 반환 + CORS `expose_headers` 추가 (`main.py`, CORS 보다 바깥에 등록 → preflight 에도 부여)
  - **설계 변경**: contextvars 는 요청 *시작* 시 clear (종료 시 X). 종료 시 비우면 바깥 `ServerErrorMiddleware` 의
    500 핸들러가 request_id 를 잃는다. 요청마다 task(컨텍스트)가 분리돼 누수 없음 — 테스트로 확인
  - 500 응답은 미들웨어 바깥에서 만들어져 `core/exceptions.py` `_unhandled` 가 contextvars 에서 읽어 헤더를 직접 붙임
  - BaseHTTPMiddleware 미사용 — 하위 앱을 별도 task 로 돌려 dependency 가 바인딩한 user_id 가 미들웨어로 안 돌아옴
  - [ ] **(직접)** 엣지 nginx `proxy_set_header X-Request-ID $request_id;` → nginx 로그와 연결 (레포 밖: `~/rekit/nginx`).
        nginx `$request_id` (hex 32자) 는 위 검증을 통과하므로 그대로 이어받는다
- [x] **O1-3 인증 사용자 컨텍스트 (2026-11-05 완료)** — `get_current_user` 가 인증 성공 시에만 `bind_contextvars(user_id=...)`
  (비활성/위조 토큰으로 거절된 요청엔 안 붙음). 관리자 작업 로그의 "누가" 도 이 값
- [x] **O1-4 구조화 액세스 로그 (2026-11-05 완료)** — 이벤트 `http_request`, logger `app.access`:
      `method, path(라우트 템플릿), status, duration_ms, client_ip` + 컨텍스트 `request_id, user_id`
  - path 는 FastAPI 가 남기는 `scope["route"].path` (예 `/api/v1/orders/{order_number}`). 매칭 실패는 `<unmatched>`
    (스캐너 무작위 경로로 값 종류 폭발 방지. CORS preflight 도 라우팅 전 응답이라 `<unmatched>`)
  - 미처리 예외로 응답 시작 전에 빠져나가면 status 500 으로 기록
  - gunicorn `--access-logfile -` 제거 (`Dockerfile` CMD, `docker-compose.prod.yml` command) +
    `configure_logging` 이 `uvicorn.access` 를 WARNING 으로 → 로컬 `uvicorn --reload` 포함 이중 기록 없음
  - `/health`, `/health/ready`, `/metrics` 제외 (request_id 헤더는 부여)
  - client_ip 는 `scope["client"]` — uvicorn proxy headers(FORWARDED_ALLOW_IPS="*") 가 X-Forwarded-For 로 치환한 값
- [x] **O1-5 민감정보 마스킹 processor (2026-11-05 완료)** — `app/core/logging.py` `mask_sensitive_fields`,
      ProcessorFormatter 체인(렌더 직전)에 연결 → stdlib·structlog 로그 모두 적용
  - 키 이름(소문자) 기준. `password`/`token`/`secret`/`authorization` **부분 일치**(new_password·client_secret·id_token 포함)
    + `ci`/`di` 정확 일치 → `***`. `payment_key` 앞 6자, `*phone*` 앞3·뒤4(구분자 유지), `*email*` 로컬파트 앞 2자. 중첩 dict/list 재귀
  - **한계**: `event` 문구·SQL 로그 본문 안에 섞인 값은 못 가림 → 민감값은 반드시 키워드 인자로.
    DEBUG=true 의 SQL 로그는 바인딩 파라미터(로그인 아이디 등)를 그대로 출력 — 운영 DEBUG 금지
    (추가 하드닝 후보: 운영 engine `hide_parameters=True` — DB 예외 메시지 속 파라미터도 숨김)
    - [ ] 2026-11-05 사용자 결정으로 보류
- [x] **O1-6 기존 로그 호출부 정비 (2026-11-05 완료)** — 18곳 전부 `structlog.stdlib.get_logger(__name__)` + 키워드 인자로 전환
  - 대상: `payment_service.py`(8), `abandoned_order_sweeper.py`(2), `auth_service.py`(4), `adapters/{kakao,naver,google}_oauth.py`,
    `core/exceptions.py`. `pg_tid` 는 마스킹 대상이 되도록 키 이름 `payment_key` 로 통일
  - 주의: `logger.info("...", event=...)` 처럼 `event` 를 키로 쓰면 structlog 예약어와 충돌 → `event_type`
  - `cache_logger_on_first_use=False` 로 변경 — 캐시하면 첫 사용 시점 설정에 고정돼 `structlog.testing.capture_logs` 와
    configure 재호출이 반영 안 됨
  - JSON `ensure_ascii=False` — 한국어 이벤트명이 `\uXXXX` 로 깨지지 않아 `docker logs | grep "토스 웹훅 수신"` 가능
  - **이벤트명 규칙**:
    1. `event` 는 **값이 섞이지 않은 고정 한국어 문구** (예 `"주문 생성"`, `"토스 웹훅 수신"`). 값은 전부 snake_case 키워드 인자
    2. 같은 사건은 같은 문구 하나 — 사유 구분은 `reason`, 경로 구분은 `method`/`operation` 키로 (예 `"로그인 실패", reason=...`)
    3. 민감값은 마스킹 규칙의 키 이름으로 넘긴다 (`email=`, `phone=`, `payment_key=`) — 다른 이름이면 안 가려짐
    4. 상태값은 Enum `.value` 문자열, 금액은 정수(원), 시간은 로그 timestamp 사용 (별도 키 X)
    5. 레벨: 정상 흐름·정상 거절 INFO / 사람이 볼 필요 있는 이상 징후 WARNING / 데이터·돈 정합성 위험·외부 장애 ERROR
- [x] **O1-7 로그 보강 (2026-11-05 완료)** — 테스트 `tests/test_service_logs.py` (19건, `capture_logs`)
  - 로그인: `"로그인 성공"`(user_id, method=password|kakao|naver|google) / `"로그인 실패"`(reason=unknown_login_id|inactive|wrong_password, WARNING).
    없는 아이디는 **입력 원문을 남기지 않음**(아이디 칸에 비번 입력 사례) — 존재 계정만 user_id 로
  - 회원: `"회원 탈퇴"`(user_id, method), `"비밀번호 변경"`(user_id, was_temp_password)
  - 주문: `"주문 생성"`(order_number, total_amount, item_count), `"주문 취소"`(previous_status), `"환불 요청"`
  - 관리자: `"관리자 주문 상태 변경"`(from_status, to_status), `"관리자 주문 취소"`(previous_status, reason), `"관리자 송장 입력"`
  - 외부 API: `"토스 API 오류 응답"`(operation, status_code, error_code) / `"토스 API 통신 실패"`(operation, error) /
    `"Octomo API 오류 응답"` / `"메일 발송 실패"`(to_email 마스킹, error) — 모두 ERROR
  - `BusinessError` → `"비즈니스 예외"`(code, status) INFO (`core/exceptions.py`)
  - **미적용**: S3 (presign 은 로컬 서명이라 실패 지점 적음, `ensure_bucket` 실패는 기동 실패로 드러남) /
    외부 API **소요시간** — O2 메트릭 `rekle_pg_request_duration_seconds` 등으로 처리 예정
- [x] **O1-8 로컬 확인 (2026-11-05 완료)** — `APP_ENV=production gunicorn -w 1` (127.0.0.1:8011) 실측:
  - 들어온 `X-Request-ID` 이어받음 / 없으면 UUID 생성해 응답 헤더 반환 / 인증 요청 액세스 로그에 `user_id`
  - path 템플릿·`<unmatched>`·`비즈니스 예외 code=ORDER_NOT_FOUND`·`로그인 실패 reason=unknown_login_id` 확인, uvicorn.access 0줄
- **O1 남은 한계 / 발견 사항**
  - [x] **500 응답에 CORS 헤더 없음 (기존 버그) — 2026-11-05 해결** — Starlette 는 `Exception` 핸들러를
        `ServerErrorMiddleware`(모든 사용자 미들웨어 바깥)에 붙인다 → `Access-Control-Allow-Origin` 누락 → 브라우저는
        500 을 CORS 에러로 표시. 해결: `UnhandledExceptionMiddleware`(app/core/middleware.py) 를 **가장 안쪽**
        사용자 미들웨어로 추가 — 라우트의 미처리 예외를 CORS 안쪽에서 표준 500 으로 바꿔 CORS·request_id 를 거쳐 나감.
        로그는 1번만(재발생 안 함). 응답 시작 후(스트리밍 도중) 예외는 바꿀 수 없어 재발생 → 기존 `_unhandled` fallback.
        미들웨어 순서는 `main.install_middlewares()` 한 곳에서 관리, 순서 회귀 테스트 있음
  - [x] **액세스 로그 path 에서 `/api/v1` 누락 (운영 이미지만) — 2026-11-05 해결** — FastAPI 0.162+ 는 `include_router`
        가 라우트를 평탄화하지 않아 `scope["route"].path` 에 바깥 prefix 가 빠진다(0.136 은 포함). 기존 테스트는
        `@app.get` 직접 등록한 미니 앱이라 재현 불가였음. 해결: 템플릿에 실제 path 파라미터를 채운 꼬리로 원본 경로에서
        prefix 를 복원(비공개 `scope["fastapi"]["included_router"]` 미사용). 2단 prefix 라우터 + 실제 `app.main.app` 테스트 추가
  - [x] **gunicorn master 로그 포맷 — 2026-11-05 해결** — 레포 루트 `gunicorn.conf.py`(O2-5 에서도 사용) 의
        `logconfig_dict` = `app.core.logging.gunicorn_logconfig_dict()` → master 로그(`Booting worker` 등)도 앱과 같은
        JSON·UTC (`build_formatter` 공용). 워커 클래스·수·바인드·errorlog 도 conf 로 옮기고 Dockerfile CMD·compose command 는
        `gunicorn -c gunicorn.conf.py app.main:app` 만
  - [ ] **⚠️ 롤백 호환성 (배포 분석 ②와 같은 문제가 더 커짐)** — deploy 잡은 master 의 compose 를 쓰는데 이제 command 가
        `-c gunicorn.conf.py` — 이 파일이 없는 0.0.5 이전 이미지로 롤백하면 기동 실패. Jenkinsfile.deploy 에서 compose 를
        배포 태그에 맞추는 수정이 선행돼야 함
  - Python warnings(`StarletteDeprecationWarning` 등)는 `warnings` 모듈이 stderr 로 직접 써서 JSON 이 아님 — 기동 시 몇 줄
  - 로컬 venv(Python 3.13, FastAPI 0.136) ≠ 운영 이미지(Python 3.11, FastAPI 0.162) — 버전 의존 동작은 이미지에서도 검증 필요

### O2. 애플리케이션 메트릭 (Prometheus) — ✅ 2026-11-05 완료 (O2-6 nginx 확인만 남음)

- [x] **O2-1 의존성** — `prometheus-client` 만 추가. **계획 변경**: `prometheus-fastapi-instrumentator` 는 안 씀 —
      자체 라우트 이름 해석이 FastAPI 0.162 중첩 라우터에서 `/api/v1` 을 잃을 위험(O1 에서 실제로 겪은 문제).
      HTTP 메트릭은 `RequestContextMiddleware` 가 액세스 로그와 **같은 path 템플릿·status** 로 기록
- [x] **O2-2 HTTP 계측** — `app/core/metrics.py` + 미들웨어
  - `rekle_http_requests_total{method,path,status}` · `rekle_http_request_duration_seconds{method,path}`
    (구간 0.025~5s, SLO 근처 촘촘) · `rekle_http_requests_in_progress` (livesum)
  - `/health`·`/health/ready`·`/metrics` 제외, 미매칭 경로는 `<unmatched>` (카디널리티 방지) — 테스트로 고정
- [x] **O2-3 비즈니스 메트릭** — 정의는 `app/core/metrics.py` 한 곳
  - `rekle_payment_confirm_total{result=success|failed|unknown}` — **PG 호출 결과만** 셈 (금액 불일치 등 사전 거절 제외)
  - `rekle_pg_request_duration_seconds{operation=confirm|get_payment|get_payment_by_order_id|cancel}` — 토스 어댑터
  - `rekle_payment_webhook_received_total{remote_status}` — 조회 API 로 재확인한 실제 상태별
  - `rekle_orders_created_total`, `rekle_signups_total{provider=email|kakao|naver|google}`, `rekle_abandoned_orders_released_total`
  - 테스트 `tests/test_business_metrics.py` (전후 차이로 검증)
  - [x] **(2026-11-10 완료)** `rekle_external_request_duration_seconds{service,operation,outcome}` — service =
        octomo·smtp·s3·kakao·naver·google·redis. 헬퍼 `observe_external_call()` (예외가 빠져나가면 `outcome=error`).
        S3 는 네트워크 호출만(presign 제외, head 404 는 ok), Redis 는 `InstrumentedRedis.execute_command` 한 곳(pipeline 미사용).
        테스트 `tests/test_external_request_metrics.py`(21)
- [x] **O2-4 DB 커넥션 풀** — `rekle_db_pool_connections_in_use` (livesum), pool `checkout`/`checkin` 이벤트로 갱신.
      scrape 시점에 pool 을 읽으면 그 워커 하나 값만 보여 멀티 워커에서 틀림. `engine.dispose()` 후에도 유지 확인
- [x] **O2-5 gunicorn 멀티프로세스** — **계획 변경**: compose `rm -rf` 대신 `gunicorn.conf.py` hook 으로 자체 완결
  - `on_starting`: `PROMETHEUS_MULTIPROC_DIR`(기본 `/tmp/prometheus_multiproc`) 설정 + 이전 파일 삭제.
    파일 최상단이 아닌 hook 에서 하는 이유 — conf 를 읽기만 하는 테스트까지 멀티프로세스 모드로 안 바뀌게
  - `child_exit`: `mark_process_dead(pid)`. 로컬 uvicorn 은 env 없음 → 단일 프로세스
  - **실측**: `gunicorn -c gunicorn.conf.py` 워커 4개, 요청 20건 → `/metrics` 6회 수집 모두 정확히 20
- [ ] **O2-6 `/metrics` 비공개 확인 (직접)** — 메모리상 엣지 nginx 는 `/api/`·`/health` 만 앱으로 넘겨서 외부 미노출 예상.
      배포 후 `curl https://rekit.co.kr/metrics` 가 앱 응답(`rekle_` 텍스트)이 아닌지 확인. nginx 라우팅을 넓히면
      `location = /metrics { return 404; }` 필수. Prometheus 는 내부망 `rekle-app:8000/metrics` 로 수집
- [x] **O2-7 테스트** — `tests/test_metrics.py`(12)·`test_business_metrics.py`(10)·`test_gunicorn_conf.py`(3)
      (O2-8·O2-9·O4b 로 `test_metrics.py` +3, `test_gunicorn_conf.py` +4, 신규 `test_event_loop_lag.py`(4)·
      `test_database_timeouts.py`(4)·`test_redis_client.py`(2))
- [x] **O2-8 이벤트 루프 지연 메트릭 (2026-11-05 완료)** — `rekle_event_loop_lag_seconds` Histogram(0.005~2.5s).
      `app/core/event_loop_lag.py` — `asyncio.sleep(interval)` 이 예정보다 늦게 깨어난 만큼 = 루프가 막힌 시간.
      lifespan 백그라운드 태스크(스위퍼와 함께 cancel), 주기 `EVENT_LOOP_LAG_INTERVAL_SECONDS`(기본 0.5, 0=끔).
      테스트는 `time.sleep(0.1)` 블로킹으로 지연 관측 확인. Grafana p99/p50 패널 추가 → O8-1 직접 검증용
- [x] **O2-9 DB 풀 대기 시간·타임아웃 (2026-11-05 완료)** — `rekle_db_pool_checkout_wait_seconds` Histogram +
      `rekle_db_pool_timeouts_total`. pool `checkout` 이벤트는 획득 *후* 라 대기를 못 재서, `AsyncAdaptedQueuePool`
      서브클래스(`InstrumentedAsyncAdaptedQueuePool`)의 공개 `connect()` 를 감싸 잼 (대기 + 새 커넥션 생성 + pre_ping 포함).
      `_do_get` 은 경합 시 재귀라 이중 관측돼 제외. dispose 후 재생성 풀도 같은 클래스 → 계측 유지. Grafana 패널 2개
- **O2 한계 메모** — `prometheus_client` 멀티프로세스 모드는 `process_*`(CPU·메모리) 메트릭을 노출하지 않는다
  → 소크 테스트의 메모리 누수 관찰은 cAdvisor(O5-3) 필수

### O3. 에러 추적 (Sentry) — 코드 ✅ 2026-11-05 완료, DSN 발급·검증은 직접

- [ ] **O3-1 Sentry 프로젝트 생성 (직접)** (무료 플랜) → DSN 을 운영 시크릿 `~/rekit/secrets/rekit_backend.env` 의 `SENTRY_DSN` 에
- [x] **O3-2 SDK 연동** — `app/core/sentry.py` `init_sentry()`, `create_app()` 에서 호출. `SENTRY_DSN`(비면 비활성) ·
      `SENTRY_TRACES_SAMPLE_RATE` · `APP_VERSION` 3곳 반영
  - **계획 변경**: traces 기본 **0.0**(에러만) — 무료 플랜 트랜잭션 한도·오버헤드. 필요 시 env 로 올림
  - **계획 변경**: `SENTRY_ENVIRONMENT` 별도 변수 없이 `APP_ENV` 사용
  - `release` = `APP_VERSION` — compose 가 `${IMAGE_TAG}` 로 주입 (IMAGE_TAG 는 원래 이미지 선택에만 쓰여 컨테이너엔 없었음)
  - `send_default_pii=False` + `EventScrubber`(Sentry 기본 목록 + `payment_key`·`phone`·`email`·`ci`·`di`, 재귀)
  - `BusinessError` 는 `before_send` 에서 제외
- [x] **O3-3 request_id·user_id 태그** — `before_send` 가 structlog contextvars 에서 읽어 `tags.request_id`·`user.id`
- [x] **O3-4 "사람이 즉시 봐야 하는" 이벤트** — **계획 변경**: `capture_message` 를 곳곳에 넣지 않음.
      Sentry LoggingIntegration 기본값이 ERROR 로그를 이벤트로 보내므로, 이미 ERROR 로 남기는 결제 이상
      (취소된 주문의 승인 감지·웹훅 금액 불일치 등)·스위퍼 실패(`logger.exception`)·미처리 예외가 자동으로 잡힌다
- [ ] **O3-5 검증 (직접)** — DSN 넣고 스테이징/운영에서 의도적 예외 1회 → 이슈·스택트레이스·request_id 태그 확인

### O4. 헬스체크 — ✅ 2026-11-05 완료 (O4-3·O4-4 남음)

- [x] **O4-1 liveness / readiness 분리** — `app/core/health.py`
  - `/health` — 프로세스 생존만 (의존성 안 봄 — DB 장애 때 재시작 반복 방지)
  - `/health/ready` — DB `SELECT 1` + Redis `PING` 동시 실행, 각 2초 타임아웃, 결과 `ok|fail|timeout` + 실패 시 503.
    `get_readiness_checks` Depends 로 테스트에서 장애 주입. OpenAPI 비노출. 실측 200 확인
- [x] **O4-2 compose `healthcheck`** — app 서비스 `curl -fsS http://127.0.0.1:8000/health` (30s/5s/3회, start_period 40s)
- [ ] **O4-3 외부 업타임 모니터 (직접)** — UptimeRobot 또는 Uptime Kuma → `https://rekit.co.kr/health/ready` 1분 주기.
      ⚠️ 엣지 nginx 가 `/health` 외에 `/health/ready` 도 앱으로 넘기는지 확인 필요 (prefix 매칭이면 자동)
- [ ] **O4-4 방치 주문 스위퍼 단일 실행 검토** — 현재 `lifespan` 에서 gunicorn 워커 4개가 각자 스위퍼 기동.
      `SKIP LOCKED` 로 정합성은 안전하나 토스 조회·DB 쿼리 4배. Redis 락(leader 1개) 또는 별도 프로세스로 분리 검토

### O4b. 타임아웃·보호 설정 (부하 시 "무한 대기" 방지 — 부하테스트 전 선행)

- [x] **O4b-1 DB 풀 `pool_timeout` (2026-11-05 완료)** — `DATABASE_POOL_TIMEOUT`(기본 5초). 초과 시
      `sqlalchemy.exc.TimeoutError` 전용 핸들러 → **503 `SERVICE_BUSY`** 표준 에러 포맷 (내부 메시지 비노출, WARNING 로그).
      api.md §1.5 에 코드 추가. 타임아웃 횟수는 O2-9 카운터
- [x] **O4b-2 Postgres `statement_timeout` · `idle_in_transaction_session_timeout` (2026-11-05 완료)** —
      asyncpg `connect_args={"server_settings": ...}`, `DATABASE_STATEMENT_TIMEOUT_MS`(10000)·
      `DATABASE_IDLE_IN_TRANSACTION_TIMEOUT_MS`(30000), 0=끔. 실제 커넥션의 `pg_settings` 로 검증.
      `alembic/env.py` 는 별도 엔진(`async_engine_from_config`)이라 마이그레이션엔 적용 안 됨 (긴 DDL 안전)
- [x] **O4b-3 Redis 클라이언트 타임아웃 (2026-11-05 완료)** — `REDIS_SOCKET_TIMEOUT`·`REDIS_SOCKET_CONNECT_TIMEOUT`
      (2.0초)·`REDIS_MAX_CONNECTIONS`(워커당 50). 기본 `ConnectionPool` 은 상한 초과 시 대기 없이 즉시 ConnectionError —
      부하테스트에서 걸리면 상한 상향 또는 `BlockingConnectionPool` 검토
- [x] **O4b-4 gunicorn 튜닝값 명시 (2026-11-05 완료)** — `timeout=30`(async 워커에선 요청 타임아웃이 아닌 하트비트 —
      루프가 30초 막히면 워커 재시작)·`graceful_timeout=8`(docker stop 기본 유예 10초 안)·`keepalive=75`(nginx upstream
      `keepalive_timeout` 기본 60초보다 길게 — 짧으면 간헐 502)·`max_requests=10000`+`jitter=1000`. 테스트 4건 추가
  - [ ] **(직접) 엣지 nginx 확인** — `~/rekit/nginx` upstream 의 `keepalive_timeout` 이 60초 이하인지
  - [x] **(2026-11-10 완료) compose `command` 에 `exec gunicorn`** — sh 가 PID 1 로 남으면 SIGTERM 이 gunicorn 에 안 가
        graceful_timeout 무의미. prod·로컬 compose 모두 `exec` (Dockerfile CMD 는 원래 exec form). `tests/test_compose_config.py`
- [ ] **O4b-5 rate limit** — 로그인은 bcrypt 로 요청당 CPU 가 큰 엔드포인트 → 그 자체로 DoS 경로. 부하테스트·공개 전 선행 검토

### O5. 모니터링 스택 (Prometheus + Grafana + exporter) — 로컬 ✅ 2026-11-05, 운영 구성 남음

- [x] **O5-0 로컬 스택** — `infra/monitoring/docker-compose.yml` (prom/prometheus v3.5.0 · grafana 12.1.0, loopback 만)
  - Prometheus → `host.docker.internal:8000` (Mac 의 uvicorn) 15초 수집, 보존 7일. **nginx 불필요**
  - Grafana provisioning — 데이터소스 + "Rekle 서비스" 대시보드(`grafana/dashboards/rekle-service.json`, 13패널:
    RPS·p95·5xx·in-progress·DB pool·결제 결과·토스 p95·주문/가입·웹훅·방치 주문 + 루프 지연 p99·풀 대기 p95·풀 타임아웃). 로컬 전용 익명 로그인
  - 실측: target up, 요청 60건이 경로·status 별 집계, Grafana→Prometheus 쿼리 60
- [x] **O5-1 운영 구성 위치 (2026-11-10 결정)** — 운영 서버에 **별도 compose 프로젝트**(`rekle-monitoring`), 포트 전부
      127.0.0.1 → SSH 터널 또는 엣지 nginx `/grafana/`. 네트워크 이름은 env 로 받아 다른 서버 이전 쉬움
- [x] **O5-2·O5-3 운영 Prometheus + exporter (2026-11-10 코드 완료)** — `infra/monitoring/prod/` (사용법 `docs/monitoring.md`)
  - Prometheus v3.5.0(30d/10GB, remote-write 수신) · Alertmanager v0.28.1 · node-exporter · cAdvisor · postgres-exporter · redis_exporter
  - scrape: rekle-app·node·cadvisor·postgres·redis·`seaweedfs:9324`. 앱 네트워크 `rekit-backend_default`(운영 실측 확인 —
    postgres·redis 는 이 네트워크에만 있음) + `rekit_edge` + `seaweedfs_default`
  - 로컬 Mac 에서 기동 검증 (cAdvisor 컨테이너별 지표는 Docker Desktop 한계로 미확인 — 운영 Linux 에서 확인 필요)
  - [x] **운영 배포 (2026-11-10 완료)** — 서버 `~/rekit/monitoring` (레포 `infra/monitoring` 을 `git archive` 로 복사 —
        **자동 동기화 없음**), 시크릿 `~/rekit/secrets/rekle_monitoring.env`(600, 비밀번호는 서버에서 무작위 생성),
        PG 계정 `rekle_monitor`(`pg_monitor`, 커넥션 3) 생성, 컨테이너 7개 기동 → 수집 대상 8개 up
  - [ ] **(직접) 슬랙 웹훅** — `~/rekit/secrets/monitoring/slack_webhook_url` + 디렉터리 755·파일 644(Alertmanager 는
        nobody 사용자) → `docker restart rekle-mon-alertmanager`. **그 전까지 알림은 판정만, 전송 안 됨**
  - [x] **SeaweedFS 메트릭 (2026-11-10 완료)** — `~/rekit/seaweedfs` command 에 `-metricsPort=9324`(publish 안 함) → target up
  - [x] **SeaweedFS 포트 외부 노출 차단 (2026-11-10 완료)** — 9333·8080·8888·8333 을 `127.0.0.1:` 바인딩 (docker publish 는
        ufw 우회라 compose 에서 막음). 외부 4포트 응답 없음 · `/s3/` 이미지 200 확인. 데이터 백업
        `~/rekit/seaweedfs/data-backup-20261110-141659.tar.gz`. 관리 화면은 `ssh -L 8888:localhost:8888 -L 9333:localhost:9333 externalhost`
  - [ ] **⚠️ SeaweedFS S3 인증** — 운영 command 에 `-s3.config` 없음 + 서버 안 `localhost:8333/` 익명 GET 200(버킷 목록
        익명 허용 정황) → `/s3/` 는 nginx 로 공개 경로라 **키 없이 쓰기·삭제 가능성**. `anonymous` 에 `Read:rekle-images` 만,
        앱 키에 Read·Write·List — 적용 후 이미지 GET·익명 List 거부·**관리자 업로드(사용자 직접)** 확인
- [x] **O5-4 `pg_stat_statements` (2026-11-10 코드 완료)** — prod·로컬 compose postgres `command` 에 preload +
      alembic `a7c3e9f1b2d4` (`CREATE EXTENSION IF NOT EXISTS`). 로컬 실측 조회 OK.
      **⚠️ 다음 배포 때 Postgres 컨테이너 재생성(Jenkins `up -d postgres redis app`) = 수 초~수십 초 다운타임** →
      저트래픽 시간, 직전 `pg_dump`, 배포 후 `SHOW shared_preload_libraries` 확인
- [x] **O5-5 운영 Grafana (2026-11-10 코드 완료)** — 익명 접근 없음, admin 비밀번호 미설정 시 기동 거부.
      `GF_SERVER_ROOT_URL`·`SERVE_FROM_SUB_PATH` env 로 `/grafana` 서브경로 지원. 대시보드: 서비스(외부 호출 행 추가)·
      인프라(호스트·컨테이너·PG·Redis·SeaweedFS·앱 측 S3)·부하테스트(k6 + 서버 지표 한 시간축). SeaweedFS 공식
      대시보드는 컴포넌트별 job 전제라 `weed server` 단일 구성과 안 맞아 직접 작성
  - [x] **엣지 nginx `/grafana/`·`/jenkins/` (2026-11-10 완료)** — `~/rekit/nginx/conf.d/rekit-ops.inc` 를 **443 블록에만**
        include. Jenkins `JENKINS_OPTS=--prefix=/jenkins` + `rekit_edge` 망 + Jenkins URL 변경 + **8081 `127.0.0.1` 로 차단**
  - [ ] (장기) 같은 출처(rekit.co.kr) 위험 → 서브도메인 분리 또는 nginx IP 제한·`auth_basic`
  - [x] **nginx ↔ 앱 request_id 연결 (2026-11-10 완료, O1-2 남은 항목)** — `/api/`·`/health` 에
        `proxy_set_header X-Request-ID $request_id`, `conf.d/00-log-format.conf` 의 `log_format rekit`(`rid=`·`rt=`·`urt=`).
        종단 검증: 같은 ID 가 nginx·앱 로그에 찍힘, 클라이언트 위조 헤더는 무시됨
  - 발견: nginx → 앱 사이 keepalive 없음(요청마다 새 연결, HTTP/1.0) → gunicorn `keepalive 75` 경합 없음. O8 최적화 후보로만
- [ ] **O5-6 로그 수집 — Loki + Grafana Alloy** (2026-11-10 계획 확정, 다음 작업)

  **왜 지금** — 로그가 docker json-file(`/var/lib/docker/containers/<id>/*-json.log`)에만 있어서
  ① **컨테이너 재생성 = 로그 삭제** — 배포마다 rekle-app 이전 로그가 사라짐 (2026-11-10 0.0.6 배포 직후 101줄만 남음)
  ② nginx·jenkins·seaweedfs·registry·certbot·rekle-web 은 **로테이션 없음**(`/etc/docker/daemon.json` 없음 → 무제한, nginx 8월부터 ≈26MB)
  ③ 조회는 `ssh` + `docker logs | grep` 뿐 — 메트릭 이상 시점에서 로그로 못 넘어감

  **결정** — Loki + **Grafana Alloy**. Promtail 은 **지원 종료(EOL)** 라 새로 도입하지 않는다.
  ELK/OpenSearch 는 서버 1대(4코어·15GB)에 JVM 2~4GB+ 라 과함 (로그량 하루 수 MB). 개념 비교는 Obsidian 「모니터링 구조」

  - [ ] **O5-6-1 이미지·버전** — `grafana/loki`(3.x), `grafana/alloy`(v1.x) **정확한 태그 고정**(2주 이상 지난 안정 버전,
        릴리스 노트 확인). 기존 스택처럼 `x-logging` 로테이션 적용
  - [ ] **O5-6-2 Loki 설정** (`infra/monitoring/loki/loki-config.yml`, 로컬·운영 공용)
    - 단일 바이너리(monolithic), `auth_enabled: false`, 저장소 filesystem, 인덱스 `tsdb` + `schema: v13`
    - **보관 30일** — `compactor.retention_enabled: true` + `limits_config.retention_period: 720h` (compactor 없으면 retention 미동작)
    - `reject_old_samples`·수집 속도 제한 기본값 검토, 볼륨 `loki_data`
    - **호스트 포트 publish 금지**(자체 인증 없음) — Grafana·Alloy·Prometheus 는 compose 내부망 `loki:3100` 으로. 디버깅은 `127.0.0.1` 바인딩만
    - `mem_limit` 검토 (예: Loki 1g, Alloy 256m) — 쇼핑몰과 같은 서버
  - [ ] **O5-6-3 Alloy 설정** (`infra/monitoring/alloy/config.alloy`)
    - `discovery.docker` → `discovery.relabel` → `loki.source.docker` → `loki.write`
    - ⚠️ **docker.sock 접근 = 호스트 장악 가능 권한** (`:ro` 여도 API 전체). 대안 비교 후 결정:
      `tecnativa/docker-socket-proxy`(`CONTAINERS=1` 만 허용, 읽기 전용) 경유 권장
    - **라벨은 값 종류가 적은 것만**: `container`, `compose_project`, `compose_service`, `stream`(stdout/stderr), `env=prod`,
      (선택) 앱 JSON 의 `level`. **`request_id`·`user_id`·`path` 는 라벨 금지**(카디널리티 폭발) — 본문에 두고 `| json` 으로 검색
    - 위치(positions) 저장용 볼륨 — Alloy 재시작 시 중복·누락 없이 이어 읽기
    - 대상: 서버의 **모든 컨테이너** (앱·nginx·postgres·redis·seaweedfs·jenkins·모니터링 자신)
  - [ ] **O5-6-4 Grafana**
    - Loki 데이터소스 provisioning (`grafana/provisioning/datasources/`)
    - **derived field** — 로그 본문의 `request_id`(앱 JSON) / `rid=`(nginx) 를 클릭하면 같은 ID 로그 전체로 이동하는 링크
    - 대시보드: 서비스 대시보드에 "ERROR 로그" 패널 + 레벨별 로그 양, 인프라 대시보드에 컨테이너별 로그 양
    - `docs/monitoring.md` 에 LogQL 예시 (`{container="rekle-app"} | json | request_id="..."`, `level="error"`, `duration_ms > 1000`,
      nginx `|= "rid=..."`)
  - [ ] **O5-6-5 Prometheus·알림 연동** — Loki·Alloy `/metrics` scrape 추가 (기존 `MonitoringTargetDown` 이 다운 감지),
        (선택) Loki 수집 실패·드롭 지표 알림. 로그 기반 알림(예: `"토스 웹훅 금액 불일치"` 1건) 은 2차로
  - [ ] **O5-6-6 나머지 컨테이너 로그 로테이션** (레포 밖 `~/rekit/*` compose, 재생성 필요) — nginx·jenkins·seaweedfs·
        registry·certbot 에 `logging: {driver: json-file, options: {max-size: "20m", max-file: "5"}}`. rekle-web 은 프론트 레포 compose.
        `daemon.json` 기본값은 docker 데몬 재시작(전 컨테이너 중단)이 필요해 compose 방식 우선
  - [ ] **O5-6-7 로컬 스택에도 추가** (`infra/monitoring/docker-compose.yml`) — Mac Docker Desktop. ⚠️ 현재 `/Volumes/A` bind 마운트
        오류(`mkdir /host_mnt/Volumes/A: file exists`) → **Docker Desktop 재시작 후** 진행. 로컬 Prometheus·Grafana 는 5일 전 설정이라 같이 재생성
  - [ ] **O5-6-8 검증 (완료 조건)**
    - `loki -config.file=... -verify-config`, `alloy fmt`/기동 로그 오류 0, `promtool check config`
    - 앱 요청 → Grafana Explore 에서 `request_id` 로 앱·nginx 로그 동시 조회
    - **앱 컨테이너 재생성 후에도 이전 로그가 Loki 에 남아 있는지** (이번 도입의 핵심 목적)
    - 30일 retention 설정이 compactor 로그에 반영되는지, 디스크 사용량 확인
    - JSON 로그 한국어 이벤트명(`"주문 생성"` 등) 이 깨지지 않고 검색되는지 (`ensure_ascii=False`)
    - 테스트·lint·type 게이트 (`pytest -v`·`ruff check app tests`·`mypy app`) — 앱 코드 변경이 없어도 실행
  - [ ] **O5-6-9 운영 배포** — `git archive origin/master infra/monitoring | ssh externalhost 'tar -x -C ~/rekit/monitoring --strip-components=2'`
        → `cd ~/rekit/monitoring/prod && docker compose --env-file ~/rekit/secrets/rekle_monitoring.env up -d` → 위 검증을 운영에서 반복.
        `docs/monitoring.md`·Obsidian 「모니터링 구조」 에 로그 흐름 절 추가

### O6. 알림 (SLO 기반)

- [x] **O6-1 SLO 정의 (2026-11-10 완료)** — `docs/slo.md`: SLI 5개 + PromQL·30일 이동 창·제외 기준.
      기록 규칙 `prometheus/rules/rekle-slo.yml`(8개, good/total 분리 저장)
- [x] **O6-2 알림 규칙 (2026-11-10 완료)** — Alertmanager 방식. `prometheus/rules/rekle-alerts.yml` 16개
  - 앱 다운 · 5xx >2% 5분(최소 20건) · 결제 unknown(재기동 직후 새 시계열도 감지) · 토스 p95 >3s 10분 · 풀 타임아웃 ·
    루프 지연 p99 >0.5s 5분 / PG·Redis 다운 · 데드락 · PG 커넥션 80% / 디스크 80·90% · 컨테이너 재시작 /
    SeaweedFS 다운·S3 5xx / exporter 다운. CPU 는 대시보드만
  - `promtool check`·`amtool check-config`·`promtool test rules`(`prometheus/tests/`) 통과
- [ ] **O6-3 알림 채널** — Alertmanager → 슬랙(`api_url_file`, 시크릿은 git 밖) 코드 완료, 이메일은 주석 예시.
      **(직접)** 슬랙 Incoming Webhook 발급 + Sentry·UptimeRobot 채널 통일
- [ ] **O6-4 런북** — Week 7 `docs/runbook.md` 와 통합: 알림별 "확인할 대시보드 / 로그 쿼리 / 조치"

### O7. 부하테스트 (k6)

- [ ] **O7-1 스테이징 환경** — 운영과 같은 사양 서버(필요 시 클라우드 임시 서버). **운영 서버에서 실행 금지**
      (DB·Redis·앱·nginx 동거 → 테스트가 곧 장애). 부하 생성기는 서버와 다른 머신
- [ ] **O7-2 외부 연동 Fake** — 토스: 현재 Fake 제거됨(커밋 `282c34c`) → 스테이징 전용 지연 주입 Fake 재도입
      (예: 300ms, 설정으로만 활성 / 운영 기동 시 활성되면 에러). SMS·이메일도 Fake 강제
- [ ] **O7-3 시드 데이터** — 운영 예상 규모 (상품 수만 · 사용자 수천 · 주문 수만) `scripts/seed_load.py`
- [ ] **O7-4 rate limit 우회** — 인증코드 60초 제한 등 스테이징에서만 완화 (설정값)
- [ ] **O7-5 k6 시나리오** — `loadtest/` 디렉터리
  - 혼합 비율: 상품 조회·검색 70% / 로그인 10% / 장바구니·관심 15% / 주문·결제 5% (운영 후 액세스 로그로 보정)
  - `sleep` 으로 사람 같은 대기, thresholds 로 합격 기준 코드화 (`p(95)<300`, `rate<0.01`)
  - 결과를 Prometheus remote write 로 보내 Grafana 에서 서버 지표와 같은 시간축으로 확인
  - [x] **(2026-11-10 완료)** Prometheus `--web.enable-remote-write-receiver` (로컬·운영) + `rekle-loadtest.json`
    (k6 VU·p95 + 서버 지표, `testid` 변수). k6 1.1.0 실측으로 메트릭명(`k6_http_req_duration_p95`, 초 단위) 확인 —
    `K6_PROMETHEUS_RW_TREND_STATS` 사용법은 `docs/monitoring.md`
  - **정합성 시나리오**: 재고 1개 상품에 VU N명 동시 주문 → 정확히 1건 성공 (초과 판매 없음) +
    장바구니가 겹치는 다품목 동시 주문 → `pg_stat_database.deadlocks` 0 확인
- [ ] **O7-5b 토큰 사전 발급 스크립트** — VU 수천 명이 매번 로그인하면 bcrypt 가 결과를 지배 →
      시드 사용자 JWT 를 미리 발급해 k6 에 주입 (O7-3 과 함께)
- [ ] **O7-5c 엣지 nginx 경유 측정** — 앱 직접(8000) vs nginx 경유 결과가 다름(`worker_connections`·버퍼). 최소 1회는 nginx 경유
- **O7 주의** — 로컬(Mac Docker · Python 3.13 · FastAPI 0.136) ≠ 운영(Linux · 3.11 · 0.162) → 로컬은 스모크·시나리오
  검증까지만, 기준선(O7-7)은 스테이징에서
- [ ] **O7-6 테스트 종류 순서** — 스모크(1~2 VU, 1분) → 부하(예상 평시, 10~30분) → 스트레스(점증, 붕괴점 찾기)
      → 스파이크(순간 10배) → 소크(평시 수 시간, 메모리·커넥션 누수)
- [ ] **O7-7 기준선(baseline) 측정 + 기록** — `docs/perf/YYYY-MM-DD-<이름>.md`
      (조건: 커밋·서버 사양·워커 수·pool / 결과: API별 RPS·p95·에러율 / Grafana 스크린샷 / 원인 분석 / 조치)

### O8. 개선 루프 — 사전 식별된 병목 가설 (부하테스트로 검증 후 하나씩)

> 한 번에 **하나만** 바꾸고 같은 시나리오로 재측정 → `docs/perf/` 에 전후 비교 기록.

- [ ] **O8-1 bcrypt 가 이벤트 루프 블로킹** — `app/core/security.py` `hashpw`/`checkpw` 가 async 핸들러에서 동기 호출
      (1회 ~0.2–0.3초 동안 해당 워커의 모든 요청 정지). 가설 검증: 로그인 부하 시 상품 조회 p95 동반 상승.
      조치: `await asyncio.to_thread(...)` (호출부 `auth_service.py`, `user_service.py` async 화)
- [ ] **O8-2 DB 커넥션 수** — 워커 4 × (pool 5 + overflow 10) = 최대 60 vs Postgres `max_connections` 100.
      O2-4 pool 메트릭으로 대기 발생 여부 확인 후 조정 (워커 증설 시 재계산)
- [ ] **O8-3 N+1 쿼리** — `pg_stat_statements` 호출 수 상위 쿼리 확인 → 상품 목록·주문 목록·관리자 목록 `selectinload` 점검
- [ ] **O8-4 인덱스** — 느린 쿼리 `EXPLAIN ANALYZE` → 누락 인덱스 마이그레이션
- [ ] **O8-5 캐싱 후보** — 카테고리·featured 상품 등 읽기 많은 응답 Redis 캐시 (측정 후 효과 있을 때만)
- [ ] **O8-6 워커 수 튜닝** — `-w` 값을 CPU 코어 기준으로 측정 비교 (2·4·코어×2)
- [x] **O8-7 상품 락 순서 고정 (데드락 방지) (2026-11-05 완료)** — `get_products_with_lock` 에 `.order_by(Product.id)`.
      장바구니가 겹치는 동시 주문이 항상 id 순으로 락을 잡음. 통합 테스트가 실제 실행 SQL(`before_cursor_execute`)에서
      `ORDER BY products.id` + `FOR UPDATE` 확인 (정합성 문제라 측정 없이 선반영)
- [ ] **O8-8 httpx 클라이언트 공유** — 토스·OAuth·Octomo 어댑터가 호출마다 `httpx.AsyncClient` 새로 생성 →
      매번 TCP+TLS 핸드셰이크. lifespan 에서 공유 클라이언트(커넥션 풀) → `rekle_pg_request_duration_seconds` 전후 비교
- [ ] **O8-9 상품 검색** — `catalog_repository` 의 3컬럼 `ILIKE '%x%'` + 매 페이지 `count(*)` 서브쿼리 + `OFFSET`
      → 상품 수만 건에서 페이지당 전체 스캔 2회. 후보: `pg_trgm` GIN 인덱스 / count 캐싱

### O9. (확장 — 규모 커지면)

- [ ] OpenTelemetry 분산 트레이싱 (Tempo/Jaeger) — 서비스 분리·외부 호출 증가 시
- [ ] 로그 핫/콜드 계층 (최근 2주 Loki / 이후 S3) — 보관 의무·비용 이슈 생길 때
- [ ] 쿠버네티스 전환 시 컨테이너당 uvicorn 1프로세스 → `PROMETHEUS_MULTIPROC_DIR`·gunicorn hook 제거

---

> **분석 기준**: `/Volumes/A/web_projects/rekle` 프론트 디자인 (Vue 3 mockup, `_design/buyer/*`, `_design/admin/*`)
> **현 백엔드 상태** (2026-07-04 기준):
> - **구현 완료**: auth 전체(이메일 인증 가입 포함) / users (PATCH·DELETE /me + 휴대폰 인증 변경) / catalog (DB 동적 카테고리, bulk 조회) / admin catalog CRUD(이미지 단건 수정 포함) / admin dashboard·orders·members·sales / cart / favorites / address(label/memo) / order (환불요청·배송조회 포함) / payment (init·confirm·webhook) / uploads / **help(공지·FAQ·문의) 신규 완료 — 로그인 필수 전환 + 답변 등록 + 내 문의 조회 추가** / **Redis 인프라 신규 완료**
> - **미구현** (2026-11-05 갱신): shipment 추적 (스마트택배 API) / 인앱 알림센터(벨 아이콘) / rate limit / 보안 헤더 미들웨어 / 이메일 변경. (SMS 인증·본인인증 PG·CI/DI 암호화는 폐기, PG 환불 실호출은 완료)
> - **테스트**: 366개 통과 (단위 + 통합, `tests/integration/` 포함, 실제 Postgres 대상 통합 테스트 신규 포함) / ruff·mypy 전체 클린
> **작성일**: 2026-05-01 / **최종 업데이트**: 2026-07-04

---

## 0. 디자인 시스템에서 도출된 화면 → 백엔드 매핑

### Buyer (모바일 mockup)

| Vue 화면 | 핵심 데이터 | 사용자 액션 |
|---|---|---|
| `AuthView` | 이메일, 휴대폰, SMS 인증코드, 약관동의 | 이메일 가입/로그인, SMS 발송/검증, 소셜(카카오/네이버) |
| `HomeView` | 카테고리 8종, 신뢰 배지(동작보증/직배송/친환경), 오늘 입고된 상품 4개 | 카테고리 진입, 알림/장바구니 진입, 검색 |
| `ListView` | 상품 목록(grid), 24개 카운트, 정렬(최신/낮은가격/높은가격), 칩 필터(A급/동작보증/~30만원) | 좋아요 토글, 무한스크롤/페이지네이션 |
| `DetailView` | 다중 이미지(썸네일 6장: 정면/측면/내부/흠집/뒷면/제품번호), 등급 안내, 스펙(브랜드/모델/연식/용량/크기/무게), 배송 정보 | 좋아요, 장바구니 담기, 바로 구매 |
| `CartView` | 선택된 항목, 수량, 배송비(60,000), 직배송 할인(-20,000) | 항목 선택/삭제, 수량 ±, 주문 진행 |
| `IdentityView` | 진행 단계(인증→주문→결제), 인증 옵션(휴대폰/카드) | 본인인증 시작 |
| `OrderView` | 인증완료 표시, 배송지, 주문상품 목록, 배송방식(화물/직접), 결제수단(카드/계좌/간편) | 배송지 변경, 메모, 결제 진행 |
| `CompleteView` | 주문번호 `RK-26050001`, 결제 정보, 카드 정보(신한 1234/일시불), 배송 일정 | 주문상세/홈 이동 |
| `MyView` | 프로필, 누적 절약 kg, 인증 뱃지, 주문 카운트(결제완료/준비중/배송중/배송완료), 최근 주문, 관심상품 12개, 배송지 2개 | 메뉴 진입, 배송조회, 주문상세 |

### Admin (데스크톱 mockup)

| Vue 화면 | 핵심 데이터 | 액션 |
|---|---|---|
| `DashboardView` | KPI 4종(오늘 주문/매출/처리대기/재고부족), 최근 7일 매출 차트, 처리대기 주문 4건, 인기 카테고리, 재고 알림 | CSV 내보내기, 상품 등록 |
| `ProductsView` | 상품 표(썸네일/브랜드·모델/카테고리/등급/가격·원가/재고/상태), 칩 필터(전체/판매중/품절/비공개) | 검색, 등록, 편집 |
| `OrdersView` | 주문 표(주문번호·일시/주문자·전화/품목/금액/상태/송장번호), 상태 탭(전체/결제완료/준비중/배송중/배송완료/취소환불) | 송장 입력, 상세 보기, CSV |
| `MembersView` | KPI 4종(전체/인증/신규/구매), 회원 표(이름/이메일·전화/인증/가입일/주문수/구매액/상태) | 검색, 상세 진입 |
| `SalesView` | 월 총매출 헤드라인, KPI 3종, 일별 매출 라인차트, 결제수단별 막대, 매출 상위 상품 | 기간 선택, CSV |

---

## 1. 추가 필요 API 엔드포인트 목록

### 1.1 인증 / 회원 (`/api/v1/auth`, `/api/v1/users`)

- [x] `POST /auth/sign-up` — 이메일+비밀번호+이름 회원가입 (`login_id` 기반, `UsernameTaken`/`EmailTaken` 처리)
- [x] `POST /auth/sign-in` — 아이디/비번 로그인 (JWT access body + refresh HttpOnly 쿠키, `remember` 분기)
- [x] `POST /auth/refresh` — 토큰 갱신 (refresh 쿠키 rotation)
- [x] `POST /auth/sign-out` — refresh 쿠키 폐기
- [x] `POST /auth/check-login-id` — 아이디 중복 확인
- [x] `POST /auth/find-id` — 이메일로 아이디 발송 (BackgroundTasks + enumeration 방어)
- [x] `POST /auth/find-password` — 임시 비밀번호 발급 후 메일 발송 (BackgroundTasks)
- [x] `POST /auth/social/{provider}/callback` — 카카오/네이버/구글 OAuth (이메일 자동 연결 포함)
- [x] `POST /auth/social/sign-up` — tempToken으로 소셜 신규가입 마무리
- [x] `GET /users/me` — 내 정보 (프로필 + 소셜 연결 현황)
- [x] `POST /users/me/password` — 비밀번호 변경 (`must_change_password` 해제)
- [x] `POST /auth/email/send-verification` — **신규 완료** 회원가입용 이메일 인증코드 발송 (Redis TTL 10분, 60초 rate-limit)
- [x] `POST /auth/email/verify-code` — **신규 완료** 코드 검증 → `verifiedToken`(JWT 15분) 발급, `sign-up` 요청에 필수로 사용
- [x] ~~`POST /auth/sms/send`, `POST /auth/sms/verify` — 회원가입 단계 SMS 인증~~ — 폐기: **2026-11-05 결정: SMS 인증 안 함** — 휴대폰 인증은 Octomo(`/users/me/phone/*`)로 일원화
- [x] `PATCH /users/me` — username/phone 부분 업데이트 _(현재 인증 없이 자유변경 — §7.3 개인정보 수정 정책 참고)_
- [x] `POST /users/me/phone/send-verification` — **신규 완료** 전화번호 변경: Octomo 인증 QR 발급 (60초 rate-limit)
- [x] `POST /users/me/phone/verify` — **신규 완료** 인증코드 확인 후 `users.phone` 교체 (`OtpInvalidError` 422)
- [ ] `POST /users/me/email/send-verification` — 이메일 변경: 새 주소로 인증코드 발송 (Redis TTL 10분)
- [ ] `POST /users/me/email/verify` — 인증코드 확인 후 `users.email` 교체
- [x] `DELETE /users/me` — 회원탈퇴 (PII 전체 익명화 — email/login_id/username/phone 파기, `UserStatus.WITHDRAWN` + `withdrawn_at` 기록, 거래정보 5년 보존)
- [ ] `POST /users/me/social/connect` — 기가입 사용자 소셜 계정 추가 연결

### 1.2 본인인증 (`/api/v1/verifications`) — 폐기

> 2026-07-12 마이그레이션 `6105137b8e93` 으로 본인인증 PG(CI/DI) 대신 **Octomo 휴대폰 인증**으로 대체.
> 주문 가드는 `User.verified`(= `phone_verified_at IS NOT NULL`). verifications 엔드포인트 3종은 만들지 않는다.

### 1.3 주소록 (`/api/v1/addresses`) ✅ 구현 완료

- [x] `GET /addresses` — 내 배송지 목록
- [x] `POST /addresses` — 추가
- [x] `PATCH /addresses/{id}` — 수정 (기본 배송지 토글 포함)
- [x] `DELETE /addresses/{id}`

### 1.4 상품 — 구매자 (`/api/v1/products`) ✅ 구현 완료

- [x] `GET /products` — 목록 (query: `category`, `q`(검색), `grade`, `min_price`, `max_price`, `warranty`, `sort`(latest/price_asc/price_desc), `page`)
- [x] `GET /products/{id}` — 상세 (이미지 다중, 스펙, 등급 안내, 배송정보)
- [x] `GET /products/featured` — 홈 "오늘 입고된 상품" 4건 (`order by created_at desc, status=ACTIVE`)
- [x] `POST /products/bulk` — **신규 완료** 상품 ID 배열로 bulk 조회 (장바구니/찜 목록 렌더용)
- [x] `GET /categories` — 카테고리 목록 (DB `product_categories` 테이블 — 아이콘·대표 이미지 포함)

### 1.5 관심상품 / 찜 (`/api/v1/favorites`) ✅ 구현 완료

- [x] `GET /favorites` — 내 관심상품 목록 (My의 "관심상품 12")
- [x] `POST /favorites/{product_id}` — 추가 (멱등)
- [x] `DELETE /favorites/{product_id}` — 제거

### 1.6 장바구니 (`/api/v1/cart`) ✅ 구현 완료

- [x] `GET /cart` — 항목 + 합계 + 배송비 견적
- [x] `POST /cart/items` — 추가 (있으면 수량 합산 upsert)
- [x] `PATCH /cart/items/{id}` — 수량 변경
- [x] `DELETE /cart/items/{id}`
- [x] `POST /cart/items/bulk-delete` — 선택 삭제

### 1.7 주문 / 결제 (`/api/v1/orders`, `/api/v1/payments`) ✅ 대부분 구현 완료

- [x] `POST /orders/quote` — 배송방식별 배송비/할인 계산 (FREIGHT 60K / DIRECT 40K, zip 검증)
- [x] `POST /orders` — 주문 생성 (본인인증 가드, 배치 FOR UPDATE 락, order_number `RK-YYMMDD####`)
- [x] `GET /orders` — 내 주문 목록 (최신순, 페이지네이션)
- [x] `GET /orders/{order_number}` — 상세 (주문아이템 스냅샷, 주소 스냅샷)
- [x] `POST /orders/{order_number}/cancel` — PENDING/PAID/PREPARING 상태만 취소
- [x] `POST /payments/init` — Payment(READY) 생성 + 토스 결제창 정보 반환
- [x] `POST /payments/confirm` — 토스 서버confirm + 금액 검증 + Order PAID 전환
- [x] `POST /payments/webhooks/toss` — 수신 후 결제 조회 API 재확인 + 멱등 상태 전환 (토스 결제 웹훅엔 서명 없음)
- [x] `POST /orders/{order_number}/refund/request` — 환불 요청 (DELIVERED → PG 전액 취소 후 REFUNDED — Task 3·4 `636f00f`)

### 1.8 배송 (`/api/v1/shipments`)

- [x] `GET /orders/{order_number}/shipment` — 배송 정보
- [ ] `GET /shipments/{tracking_number}/track` — 스마트택배 API 프록시 (Redis 캐시)

### 1.9 알림 / 공지 (`/api/v1/help`, `/api/v1/notifications`)

**공지사항 / FAQ / 문의 — `app/help/` 모듈로 신규 완료** (요구사항정의서의 `announcements`에 대응, 마이그레이션 `9855aeca0293` → `f25b27344175`(답변) → `0de60b6871de`(phone 제거))

- [x] `GET /help/notices` — 공지사항 목록 (My 메뉴, 게시중만)
- [x] `GET /help/notices/{notice_id}` — 공지사항 상세
- [x] `GET /help/faqs` — FAQ 목록 (카테고리 필터) — **더미 데이터 16건 시드 완료** (`scripts/seed.py`, 주문/배송/결제/회원/상품/기타 6개 카테고리)
- [x] `POST /help/contacts` — 1:1 문의 접수 **(breaking change: 로그인 필수로 전환, `name`/`email`/`phone` 요청 바디에서 제거 — 회원 프로필 기준 자동 채움)**
- [x] `GET /help/contacts` — **신규 완료** 내 문의 목록 (페이지네이션)
- [x] `GET /help/contacts/{contact_id}` — **신규 완료** 내 문의 상세 (본인 소유만, 소유권 SQL 레벨 검증)
- [x] `GET /admin/notices`, `POST /admin/notices`, `PATCH /admin/notices/{id}`, `DELETE /admin/notices/{id}` — 공지 CRUD
- [x] `GET/POST/PATCH/DELETE /admin/faqs` — FAQ CRUD
- [x] `GET /admin/contacts`, `GET /admin/contacts/{id}`, `PATCH /admin/contacts/{id}/status` — 문의 관리 (PENDING↔ANSWERED)
- [x] `PATCH /admin/contacts/{contact_id}/answer` — **신규 완료** 답변 등록 (본문 저장 + ANSWERED 전환 + 문의자 이메일 발송)

**인앱 알림(벨 아이콘) — 미구현, 별도 모델 필요**

- [ ] `Notification` 모델 신규 (§6.11)
- [ ] `GET /notifications` — 내 알림 목록 (벨 아이콘)
- [ ] `POST /notifications/{id}/read`

### 1.10 관리자 — 대시보드 (`/api/v1/admin/dashboard`) ✅ 구현 완료

- [x] `GET /admin/dashboard/summary` — KPI 4종(오늘 주문수/매출/처리대기/재고부족) — ⚠️ 비교값(전일 대비, 긴급 카운트)은 **미구현** (§7.2)
- [x] `GET /admin/dashboard/sales-chart?period=7d|30d|90d` — 일별 막대그래프
- [x] `GET /admin/dashboard/pending-orders?limit=4` — 처리 대기 최근 주문
- [x] `GET /admin/dashboard/popular-categories` — 카테고리별 판매건수/비율
- [x] `GET /admin/dashboard/stock-alerts` — 재고 0/임박

### 1.11 관리자 — 상품 (`/api/v1/admin/products`) ✅ CRUD 구현 완료

- [x] `GET /admin/products` — 표 (필터: `status`, `q`, 페이지네이션, ADMIN role guard)
- [x] `POST /admin/products` — 등록 (이미지 URL 다중 포함)
- [x] `GET /admin/products/{id}`
- [x] `PATCH /admin/products/{id}` — 가격/재고/상태/스펙 수정 (partial update)
- [x] `DELETE /admin/products/{id}` — soft delete (`status = INACTIVE`)
- [x] `PUT /admin/products/{id}/images` — 이미지 전체 교체 (추가·삭제·순서 일괄 반영)
- [x] `PATCH /admin/products/{id}/images/{image_id}` — **신규 완료** 이미지 단건 수정 (라벨/순서 등 부분 업데이트)
- [ ] `POST /admin/products/import-csv` — Phase 우선순위 낮음
- [ ] **`AdminProductCreate`/`Update` 정수 필드 상한(`le=`)** — 정가 `100000000001` 입력 시 `INTEGER` 초과로 등록 500
      (2026-11-13 발견). 프론트 입력은 막았음(정가·판매가 10억, 재고·연도 9,999) → API 직접 호출 시 422 가 나오게
- [x] **카드용 썸네일 `product_images.thumb_url` (2026-11-13, 0.0.7)** — 마이그레이션 `660a6a71a631`(NULL 허용 컬럼 추가).
      `catalog_utils.thumbnail_url` 이 thumb 우선·url 폴백 → 카드·장바구니·찜·주문 스냅샷 공통. 이미지 응답·`PUT .../images` 에 `thumb_url`
  - [ ] 배포 후 기존 이미지 백필 — `scripts/generate_product_thumbnails.py` (stdin `id|url` → 480px WebP 업로드 + `UPDATE` SQL, dry-run 기본)

### 1.12 관리자 — 주문 (`/api/v1/admin/orders`) ✅ 대부분 구현 완료

- [x] `GET /admin/orders` — 표 (탭: 전체/결제완료/준비중/배송중/배송완료/취소환불, 카운트 포함)
- [x] `GET /admin/orders/{order_number}` — 상세
- [x] `POST /admin/orders/{order_number}/shipment` — 송장 입력 (carrier+tracking_number) → 자동 SHIPPING 상태 전환
- [x] `PATCH /admin/orders/{order_number}/status` — 수동 상태 변경 (배송완료 등)
- [x] `POST /admin/orders/{order_number}/cancel` — 관리자 취소
- [ ] `POST /admin/orders/{order_number}/refund` — 미구현 — PG 취소 연동 자체는 완료(`PaymentService.cancel_payment`, PAID/PREPARING 은 관리자 cancel 이 PG 취소까지 수행). 남은 건 DELIVERED 주문을 관리자가 환불하는 엔드포인트
- [x] `GET /admin/orders/export.csv`

### 1.13 관리자 — 회원 (`/api/v1/admin/members`) ✅ 구현 완료

- [x] `GET /admin/members/summary` — KPI 4종(전체/인증/신규/구매)
- [x] `GET /admin/members` — 표 (검색: 이름/이메일/휴대폰)
- [x] `GET /admin/members/{id}` — 상세 (가입일, 주문 이력)
- [x] `PATCH /admin/members/{id}/status` — 활성/제재 토글

### 1.14 관리자 — 매출 (`/api/v1/admin/sales`) ✅ 구현 완료

- [x] `GET /admin/sales/summary?from=&to=` — 헤드라인(총매출/주문수/평균주문/취소율) — ⚠️ 전월 대비는 **미구현** (§7.2)
- [x] `GET /admin/sales/timeseries?from=&to=&granularity=day|week`
- [x] `GET /admin/sales/by-payment-method?from=&to=`
- [x] `GET /admin/sales/top-products?from=&to=&limit=5`
- [x] `GET /admin/sales/export.csv`

### 1.15 업로드 ✅ 구현 완료

- [x] `POST /uploads/presign`
- [x] `POST /uploads/confirm`
- [x] **S3 PutObject 체크섬 설정 (2026-11-13, 0.0.7)** — botocore 1.36+ 기본(aws-chunked + CRC 트레일러)을 SeaweedFS 가
      `InvalidAccessKeyId` 로 거부 → `request/response_checksum_validation="when_required"`. 서버 경유 업로드(`/uploads/svg`)·
      스크립트가 영향. presign(브라우저 직접 PUT)은 무관. ⚠️ 운영 SVG 업로드 실제 실패 여부는 로그상 시도 없어 미확인 → 배포 후 1회 확인
- [x] **기존 상품 이미지 재압축 운영 적용 (2026-11-13)** — `scripts/recompress_product_images.py`, 12장 38.7MB → 3.0MB (-92.2%),
      키·이미지 ID·DB 무변경. 부분 실패 시 영구 skip 되던 멱등 판정 수정(백업 존재 → 크기 기준). 확인 후 `backup/originals/` 12개 삭제
- [ ] **추가 검토**: `purpose`를 `product_image` 외 `verification_doc` 등으로 확장

---

## 2. 인프라 / 공통 작업

- [x] **JWT 인증 의존성** (`Depends(get_current_user)`, `Depends(get_current_active_user)`) — `app/core/security.py` + `app/core/deps.py` 완료
- [x] **에러 응답 표준화** — `{code, message}` 포맷 + 글로벌 Exception 핸들러 (500 CORS 헤더는 2026-11-05 `UnhandledExceptionMiddleware` 로 해결 — 관측성 O1 "남은 한계" 참고)
- [x] **CORS** — `settings.cors_origins` 설정 완료, 글로벌 에러도 CORS 헤더 부착
- [x] **Pydantic 스키마** — auth/user 도메인 완료 (`app/auth/auth_schemas.py`, `app/user/user_schemas.py`)
- [x] **BackgroundTasks** — 이메일 발송 분리 (SMTP 지연이 요청 트랜잭션 묶지 않음)
- [x] **이메일 어댑터** — `ConsoleEmailSender` (개발) + `GmailSmtpEmailSender` (운영) Protocol 기반
- [x] **OAuth 어댑터** — 카카오/네이버/구글 `httpx` 기반 + `translate_oauth_error` 헬퍼 (Ports & Adapters)
- [x] **테스트** — 666개 (2026-11-05 기준) (단위 + `tests/integration/` 통합), `tests/conftest.py` 기반
- [x] **CRUD 레이어** — catalog/cart/address/order/payment/favorites/admin_catalog/help 완료
- [x] **`order_number` 생성기** — `RK-YYMMDD{id:04d}` 포맷, `app/order/order_number.py`
- [x] **Redis 통합** — **신규 완료** `app/core/redis.py` (`get_redis()` Depends 주입) — 이메일/휴대폰 인증코드 캐시 + 60초 rate-limit 에 사용 중
- [x] ~~**CI/DI 암호화 유틸**~~ — 폐기: CI/DI 컬럼 삭제(`6105137b8e93`)로 대상 없음
- [ ] **외부 연동 서비스 모듈**
  - [x] ~~SMS 발송 어댑터 (ConsoleSmsSender → NHN Cloud/알리고)~~ — 폐기: `ConsoleSmsSender` 삭제됨, 휴대폰 인증은 `app/auth/adapters/octomo.py`. **2026-11-05 결정: SMS 인증 안 함** — 휴대폰 인증은 Octomo(`/users/me/phone/*`)로 일원화
  - [x] `app/payment/adapters/toss.py` — 결제 confirm/webhook 검증 (TossPaymentGateway)
  - [x] ~~`services/toss_identity.py` / `nice_identity.py` — 본인인증 PG~~ — 폐기: Octomo 휴대폰 인증으로 대체 (§1.2)
  - [ ] `services/sweet_tracker.py` — 배송 추적 (Redis 캐시 5분)
- [x] ~~`services/social_oauth.py`~~ — 어댑터 패턴으로 `app/auth/adapters/` 에 구현 완료
- [ ] **Rate Limit** (Week 0 `rate_limit.py`·Week 7 레이트 리밋·Phase 2 #16 과 같은 항목 — 여기서 관리) — `slowapi` 의존성 있음, 미적용 (auth류 1분 10회, 일반 60회) — 이메일/휴대폰 인증코드 자체 rate-limit(60초)은 Redis로 개별 구현되어 있으나 라우터 전역 rate limit은 아직 없음
- [ ] **보안 헤더 미들웨어** (Week 0·Week 7 운영 헤더와 같은 항목 — 여기서 관리) — HSTS/X-Content-Type-Options. `app/core/middleware.py` 는 2026-11-05 request_id 미들웨어로 생성됨, 보안 헤더만 미구현
- [ ] **관리자 보안** — IP 화이트리스트 또는 2FA, OpenAPI 문서 prod 비공개 (이미 적용됨)
- [x] **통합 테스트** — `tests/integration/` 디렉터리로 신규 추가됨 (라우터 ↔ DB 결합 검증). testcontainers 도입 여부는 미확인 — 실 DB 세션 fixture 구성 방식 재확인 필요

---

## 3. 데이터/시드

- [x] 카테고리 응답: `GET /categories` — DB `product_categories` 테이블 (정적 `CATEGORY_META` 는 동적 카테고리 전환 `b427d8f8f268` 으로 제거)
- [x] 관리자 계정 부트스트랩 스크립트 — `scripts/seed.py` (재실행 안전, admin01/hong001/kim001)
- [x] 더미 상품 시드 (개발 편의) — `scripts/seed.py` 6개 상품 포함
- [x] 더미 FAQ 시드 — **신규 완료** `scripts/seed.py::seed_faqs` 16건 (6개 카테고리, 1회 존재확인 쿼리로 재실행 안전)
- [x] E2E 스모크 테스트 스크립트 — `scripts/test_api.sh` 33케이스 (멱등)
- [ ] `scripts/test_api.sh`에 `app/help/` 모듈 케이스 없음 — 문의 접수(로그인 필수)/답변/FAQ 케이스 추가 필요

---

## 4. 우선순위 (요구사항정의서 Phase에 정렬)

### Phase 1 (최소 동작)

1. ✅ JWT/Depends 정비 + auth (sign-up/sign-in/refresh/sign-out/find-id/find-password/소셜 3종, **이메일 인증코드 가입 가드 신규 완료**)
2. ✅ GET /users/me, POST /users/me/password, PATCH /users/me, DELETE /users/me(PII 익명화)
3. ✅ 상품 조회 (buyer) — `GET /products`(+bulk), `GET /products/{id}`, `GET /products/featured`, `GET /categories`
4. ✅ 주소록 CRUD (label/memo 포함)
5. ✅ 장바구니 CRUD + 관심상품 CRUD
6. ✅ ~~본인인증 PG 연동~~ → Octomo 휴대폰 인증으로 대체 (주문 가드 `User.verified`)
7. ✅ 주문 생성 + 토스 결제 confirm/webhook (멱등) + 환불 요청 + 배송 정보 조회
8. ✅ 관리자 상품 CRUD + 이미지 관리(전체 교체 + 단건 수정) + 주문 관리(송장·상태·취소·CSV) + 대시보드 + 회원 + 매출
9. ✅ 휴대폰 번호 변경 인증(`/users/me/phone/*`) — Octomo 인증, **완료**
10. ✅ 공지사항/FAQ/1:1문의 (`app/help/`) — **신규 완료**

### Phase 2 (안정화)

11. 배송 추적 자동 폴링 (Celery / 스마트택배 API) — 미구현
12. ✅ PG 환불 실호출 — 주문 취소·환불요청·관리자 취소가 PG 취소 호출 (Task 3·4). 남은 것: 관리자 DELIVERED 환불 엔드포인트 (§1.12)
13. ~~실 SMS 발송 어댑터~~ — 폐기 (Octomo 인증, SMS 인증 안 함)
14. 이메일 변경(`/users/me/email/*`) — 미구현 (회원가입 SMS 인증은 2026-11-05 결정으로 안 함)
15. 알림센터 (`Notification` 모델 + 목록/읽음) — 미구현
16. Rate limit 전역 적용, 보안 헤더 미들웨어 — 미구현 (§2 에서 관리. CI/DI 암호화는 컬럼 삭제로 폐기)

### Phase 3 (확장)

17. 후기 (리뷰), 직접배송 지역 관리, 검색 고도화, 다중 판매자

---

## 5. 모델 변경 평가 — `세부 내용은 §6` 참조 (요약)

| 모델 | 변경 필요 | 우선순위 |
|---|---|---|
| `Product` | 디자인 태그(인기/신규입고/베스트), 노출 정렬 — **선택** | 중 |
| `ProductImage` | `label`(정면/측면/...) 컬럼 추가 — **권장** | 중 |
| `User` | `status` enum(`ACTIVE`/`BANNED`/`DORMANT`/`WITHDRAWN`) — ✅ **구현 완료** (관리자 회원관리 표 "활성/제재") | 중 |
| `Order` | `discount_amount`, `shipping_method` — ✅ **구현 완료** (직배송 할인 -20k) | 상 |
| `Order` | 주문 생성 시 배송지 스냅샷에 `recipient`만 있고 가입자명 별도 필요시 — **현행 OK** | — |
| `OrderItem` | `product_image_url_snapshot` — **권장** (목록에서 이미지 노출) | 중 |
| `Payment` | `card_company`, `card_last4`, `installment_months`, `approval_number`, `pg_tid` — ✅ **구현 완료** (Complete 화면 "신한카드 1234 · 일시불") | 상 |
| `Shipment` | `direct_delivery_window_start/end` 또는 `delivery_memo_admin` — **선택** | 하 |
| **신규** `Favorite` | 관심상품 — **필수** (My "관심상품 12") | 상 |
| **신규** `Notification` | 인앱 알림 — **권장** (벨 아이콘) | 중 |
| **신규** `Announcement` | 공지사항 — **권장** (My 메뉴) | 중 |
| **신규** `ProductDirectRegion` | 직배송 가능 지역 — **선택** (Phase 3에서 충분) | 하 |

---

## 6. 모델 변경 상세

> 분석 소스: Claude Design 핸드오프 번들 `/tmp/rekle-design/extracted2/rekle/project/*.jsx` (2026-05-01 추출).
> 더미 데이터는 `design-system.jsx`의 `PRODUCTS`, `CATEGORIES`, 화면별 mock 데이터를 기준으로 한다.

### 6.1 `Product` — 상품 태그 + 노출 가중치

**현 상태** ([app/models/product.py](../app/models/product.py))
`title`, `description`, `category`, `brand`, `model_name`, `year_estimate`, `condition_grade`, `warranty_works`, `price`, `original_price`, `weight_kg`, `width/depth/height_cm`, `stock`, `status`

**디자인 신규 요구**
- 카드/타일에 `tag` 표기: `동작보증`, `인기`, `신규입고`, `베스트`, `외관용` ([screens-desktop.jsx:113](/tmp/rekle-design/extracted2/rekle/project/screens-desktop.jsx) — `{p.tag && <div ...>{p.tag}</div>}`).
- "오늘 입고된 상품" 섹션 — `created_at desc + status=ACTIVE`로 충분하나, 큐레이션을 위해 `featured_until` 필드 검토.
- 정렬 "할인율순" — `discount_pct = 1 - price/original_price` 정렬 필요.

**권장 변경**
```python
# Product에 추가
tag: Mapped[str | None] = mapped_column(String(20), nullable=True)        # "신규입고"|"베스트"|"인기"|"외관용"
featured_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 홈 노출 종료 시각
view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)        # 인기 산정용 (write-heavy → Redis 캐시 후 배치 반영 권장)
favorite_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
sold_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
```
- 정렬 `discount_desc`는 컬럼 추가 없이 SQL 표현식 `(original_price - price) * 1.0 / nullif(original_price, 0) DESC`로 처리 가능.
- `tag`를 enum으로 강제할지 자유 문자열로 둘지 — MVP는 자유 문자열, 운영 안정 후 enum화 권장.

### 6.2 `ProductCategory` enum — 8개로 확장 검토 — ⚠️ 폐기: 카테고리가 DB 테이블로 전환(`b427d8f8f268`), 추가는 `/admin/categories` 로

**현 상태**: 6개(`REFRIGERATOR`, `WASHING_MACHINE`, `TV`, `AIR_CONDITIONER`, `KITCHEN`, `ETC`).

**디자인 카테고리 노출**
- 홈 그리드 8칸: 냉장고 / 세탁기 / TV / 에어컨 / 주방가전 / **청소기** / **소형가전** / 전체 ([screens-buyer-1.jsx:102](/tmp/rekle-design/extracted2/rekle/project/screens-buyer-1.jsx)).
- 리스트 칩 7칸 + Admin 데스크톱 nav: 기획전 추가.
- 더미 PRODUCTS에 `kind: 'vacuum'` (LG 코드제로 무선청소기) 사용.

**권장 변경**
```python
class ProductCategory(str, enum.Enum):
    REFRIGERATOR = "REFRIGERATOR"
    WASHING_MACHINE = "WASHING_MACHINE"
    TV = "TV"
    AIR_CONDITIONER = "AIR_CONDITIONER"
    KITCHEN = "KITCHEN"
    VACUUM = "VACUUM"           # 신규
    SMALL_APPLIANCE = "SMALL_APPLIANCE"  # 신규 (소형가전 — 면도기/공기청정기 등)
    ETC = "ETC"
```
- 카테고리 메타(아이콘 키, 라벨, 정렬 순서)는 정적 dict로 충분 — `app/core/categories.py`로 분리.
- "전체"는 카테고리가 아니라 필터 미적용을 의미. enum에 넣지 말 것.
- "기획전(Promotion)"은 카테고리가 아니라 별도 콜렉션 — §6.10 참고.

### 6.3 `ProductImage` — 라벨 enum화

**현 상태**: `url`, `sort_order`, `label`(nullable string).

**디자인 표준 라벨 6종** ([screens-buyer-1.jsx:296-298](/tmp/rekle-design/extracted2/rekle/project/screens-buyer-1.jsx)): `정면`, `측면`, `내부`, `흠집`, `뒷면`, `제품번호`.

**권장 변경**
```python
class ProductImageLabel(str, enum.Enum):
    FRONT = "FRONT"          # 정면
    SIDE = "SIDE"            # 측면
    INSIDE = "INSIDE"        # 내부
    SCRATCH = "SCRATCH"      # 흠집
    BACK = "BACK"            # 뒷면
    SERIAL = "SERIAL"        # 제품번호
    OTHER = "OTHER"
```
- `Product`에 `thumbnail_image_id` FK 추가하면 카드 썸네일 일관성 확보. 안 하면 `sort_order=0 + label IN (FRONT, NULL)` 첫 항목 사용.
- 등록 시 정면 1장 필수, 흠집은 등급 B/C일 때 권장(서비스 레이어 검증).

### 6.4 `User` — 상태 + 누적 절약 무게

**디자인 요구**
- 회원관리 표 "활성/제재" 컬럼 ([screens-admin.jsx:325](/tmp/rekle-design/extracted2/rekle/project/screens-admin.jsx)).
- 마이페이지 "지금까지 약 86kg의 가전을 다시 살렸어요" ([screens-buyer-2.jsx:284](/tmp/rekle-design/extracted2/rekle/project/screens-buyer-2.jsx)).

**권장 변경**
```python
class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    BANNED = "BANNED"
    DORMANT = "DORMANT"   # 휴면 — 1년 무접속 (전자상거래법)

# User에 추가
status: Mapped[UserStatus] = mapped_column(Enum(UserStatus, native_enum=False, length=20), default=UserStatus.ACTIVE, nullable=False)
# is_active 는 status == ACTIVE 와 중복 — is_active 제거 또는 status로 일원화 권장
```
- 누적 절약 kg은 컬럼으로 두지 말고 **주문 완료 시점의 OrderItem.weight_snapshot 합계**로 즉시 계산하거나 캐시. 아니면 별도 `UserStat` 1행/유저로 갱신.

### 6.5 `Order` — 배송 방식 + 할인 + 본인인증 스냅샷

**디자인 요구**
- 배송 방식 선택: 화물택배 60,000원 vs 직접 배송 40,000원 ([screens-buyer-2.jsx:140-143](/tmp/rekle-design/extracted2/rekle/project/screens-buyer-2.jsx)).
- 결제 예정에 "직배송 할인 -20,000원" ([screens-buyer-1.jsx:467](/tmp/rekle-design/extracted2/rekle/project/screens-buyer-1.jsx)).
- 주문번호 포맷 `RK-26050001` ([screens-buyer-2.jsx:220](/tmp/rekle-design/extracted2/rekle/project/screens-buyer-2.jsx)).
- 주문서에 "본인인증 완료 · 박은영" 스냅샷 표시.

**권장 변경**
```python
class ShippingMethod(str, enum.Enum):
    PARCEL = "PARCEL"          # 일반택배 (소형)
    FREIGHT = "FREIGHT"        # 화물택배 (대형)
    DIRECT = "DIRECT"          # 직접 배송 (서울/경기)

# Order에 추가
shipping_method: Mapped[ShippingMethod] = mapped_column(Enum(ShippingMethod, native_enum=False, length=20), nullable=False)
shipping_fee: Mapped[int] = mapped_column(Integer, nullable=False)              # 이미 있으면 유지
discount_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 직배송 할인 등
delivery_memo: Mapped[str | None] = mapped_column(String(200), nullable=True)
identity_verified_snapshot_name: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 주문 시점의 인증 명의
```
- `total_amount = sum(items) + shipping_fee - discount_amount`. 견적 API에서 동일 식 사용.
- 주문번호는 advisory lock 또는 별도 sequence로 발급(요구사항 정의서 §5.3 멱등성 동일 원칙).

### 6.6 `Payment` — 카드 정보 표시용 필드

**디자인 요구** ([screens-buyer-2.jsx:232](/tmp/rekle-design/extracted2/rekle/project/screens-buyer-2.jsx))
> 신한카드 1234 · 일시불

**권장 변경**
```python
# ⚠️ PCI-DSS 준수
# - 토스 결제창은 브라우저 ↔ PG 간 직통 전송이라 카드 PAN이 우리 서버를 통과하지 않는다.
# - 따라서 우리는 SAQ-A 수준만 충족하면 되고, 아래 메타데이터만 저장한다.
# - 절대 저장 금지: 카드 PAN(전체번호), CVC/CVV, 유효기간(단독 저장).
# - 저장 OK: 카드사명, last4, 할부 개월, 승인번호, PG 거래ID.
card_company: Mapped[str | None] = mapped_column(String(30), nullable=True)        # "신한카드"
card_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
installment_months: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0=일시불
approval_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
pg_tid: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
# pg_tid 는 결제 confirm / webhook 의 멱등성 키. INSERT ... ON CONFLICT DO NOTHING 으로 중복 호출 방어.
```
- PG 응답에서 추출 — 카드번호 풀PAN은 절대 저장 금지 (PCI-DSS).
- 정기결제(billing_key)를 도입하게 되면 별도 암호화 컬럼 + 접근 로그 필요 — MVP 범위 외.

### 6.7 `PaymentMethod` enum — 5종 매핑 확정

매출 분석 차트의 결제수단별 5종 ([screens-admin.jsx:447-451](/tmp/rekle-design/extracted2/rekle/project/screens-admin.jsx)):
신용카드 · 계좌이체 · 카카오페이 · 네이버페이 · 토스페이.

```python
class PaymentMethod(str, enum.Enum):
    CARD = "CARD"
    BANK_TRANSFER = "BANK_TRANSFER"
    KAKAO_PAY = "KAKAO_PAY"
    NAVER_PAY = "NAVER_PAY"
    TOSS_PAY = "TOSS_PAY"
```
- 주문서 화면은 3개로 그룹("신용카드 / 계좌이체 / 간편결제") — 간편결제는 PG 위에서 카카오/네이버/토스로 분기.

### 6.8 `Shipment` — 배송 일정 범위

**디자인 요구** ([screens-buyer-2.jsx:241](/tmp/rekle-design/extracted2/rekle/project/screens-buyer-2.jsx))
> 5월 3일(토) ~ 5월 4일(일) · 직접 배송 · 도착 1시간 전 연락드려요

**권장 변경**
```python
# Shipment에 추가
estimated_delivery_from: Mapped[date | None] = mapped_column(Date, nullable=True)
estimated_delivery_to: Mapped[date | None] = mapped_column(Date, nullable=True)
direct_delivery_note: Mapped[str | None] = mapped_column(String(200), nullable=True)  # "도착 1시간 전 연락"
```
- 일반/화물택배는 carrier+tracking_number만 있어도 충분.

### 6.9 신규 모델 `Favorite` (관심상품) — **필수**

```python
class Favorite(Base, TimestampMixin):
    __tablename__ = "favorites"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
```
- 마이페이지 "관심상품 12" + 카드 우상단 하트 토글 + (이후) 가격 인하 알림.
- 멱등 INSERT (`ON CONFLICT DO NOTHING`).

### 6.10 신규 모델 `Promotion` (기획전) — **권장**

데스크톱 nav에 "기획전" 항목 + 홈 hero 보조 카드 "~5월 한정 직배송비 50% 할인" ([screens-desktop.jsx:51](/tmp/rekle-design/extracted2/rekle/project/screens-desktop.jsx)).

```python
class Promotion(Base, TimestampMixin):
    __tablename__ = "promotions"
    id: Mapped[int] = mapped_column(Identity(always=False), primary_key=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(200), nullable=True)
    banner_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
```
- 1차 배포는 hero 정적 텍스트 + 보조 배너 1~2개 정도라 정적 JSON으로도 충분. 운영자 편집이 필요해지면 위 모델로 승격.

### 6.11 신규 모델 `Notification`, `Announcement` — 이미 §5에 정리됨

알림(인앱 벨 아이콘) + 공지사항(My 메뉴) — 별도 변경 없음.

### 6.12 신규 모델 `ProductInquiry` (상품 문의) — **Phase 2~3로 보류**

대시보드 재고 알림에 "캐리어 스탠드 에어컨 — 문의 12건/재고 1" 표기 ([screens-admin.jsx:176](/tmp/rekle-design/extracted2/rekle/project/screens-admin.jsx)).
- 요구사항정의서 §1.4 "채팅/문의 실시간 기능 제외 (이메일 또는 전화 안내로 대체)" — MVP 제외 명시.
- Phase 2에서 카카오톡 채널/이메일 폼으로 대응 가능. 모델 추가 시 Question/Answer 1:N 형태.

---

## 7. 디자인 핸드오프 신규 / 변경 항목 (2026-05-01 분석 결과)

> 기준 자료: `/tmp/rekle-design/extracted2/rekle/` (Claude Design 번들)
> 기존 todo.md(같은 일자)와 비교해 **새로 생기거나 변경**되는 항목만 기재.

### 7.1 모델 변경 (마이그레이션 필요)

- [x] `ProductCategory` — enum이 아닌 동적 varchar 카테고리로 전환됨(`b427d8f8f268`) — `VACUUM`/`SMALL_APPLIANCE`는 이제 DB 시드 데이터로 추가하면 됨, 마이그레이션 불필요 (§6.2 재검토)
- [ ] `Product` — `tag`, `featured_until`, `view_count`, `favorite_count`, `sold_count` 추가 (§6.1) — 여전히 미구현
- [ ] `ProductImage` — `label`을 `ProductImageLabel` enum으로 전환, `Product.thumbnail_image_id` FK 또는 `is_primary` 추가 (§6.3) — 여전히 미구현 (현재 `label`은 nullable string)
- [x] `User` — `status: UserStatus(ACTIVE/BANNED/DORMANT/WITHDRAWN)` 추가 완료 (§6.4)
- [x] `Order` — `shipping_method`, `discount_amount` 추가 완료. `delivery_memo`, `identity_verified_snapshot_name`은 여전히 미구현 (§6.5)
- [x] `Payment` — `card_company`, `card_last4`, `installment_months`, `approval_number`, `pg_tid` 추가 완료 (§6.6)
- [ ] `Shipment` — `estimated_delivery_from`, `estimated_delivery_to`, `direct_delivery_note` 추가 (§6.8) — 여전히 미구현
- [x] **신규** `Favorite(user_id, product_id)` — composite PK 구현 완료 (§6.9)
- [ ] **신규** `Promotion` (선택, 정적 JSON 대체 가능) (§6.10) — 여전히 미구현
- [x] **신규** `Help(Notice/Faq/Contact)` — 공지/FAQ/문의 모델 구현 완료 (마이그레이션 `9855aeca0293`, §1.9 참고)
- [x] Alembic 마이그레이션은 도메인별로 개별 분할되어 진행 중 (favorites/withdrawn_at/user_status/address_label_memo/help_module 등 각각 별도 revision)

### 7.2 API 보강

- [ ] `GET /products` 정렬 옵션에 **`discount_desc`** 추가 — 기존 latest/price_asc/price_desc에 한 항목 늘림 (§6.1)
- [ ] `GET /products/featured` — 응답에 `tag` 노출 + `featured_until` 필터 적용
- [x] `POST /orders/quote` — `shipping_method` 인자에 따라 `shipping_fee`/`discount_amount` 계산 — PARCEL(일반택배 5,000원)/FREIGHT/DIRECT 모두 완료 (2026-11-05 정정 — 앞선 정리에서 PARCEL 미구현으로 잘못 기록)
  - 화물택배: 60,000원
  - 직접배송: 40,000원, 직배송 가능 지역(서울/경기) 외엔 선택 불가
  - 일반택배: 무게/사이즈 기반 (작은 가전 한정)
- [x] `POST /orders` 응답 `order_number` 포맷 확정 — `RK-YYMMDD####` (요구사항정의서/디자인 모두 일치)
- [ ] `GET /admin/dashboard/summary` 응답 필드 — KPI 4종에 **비교값 텍스트(`+3건`, `+18%`, `긴급 2`, `품절 임박`)** 포함
- [x] `GET /admin/orders` 응답에 **상태별 카운트** 동시 반환 (`AdminOrderStatusCounts`) (전체/결제완료/준비중/배송중/배송완료/취소·환불) — 탭 헤더에 표기
- [x] `GET /admin/members/summary` 응답에 **신규(이번주)** 카운트 포함 (`new_this_week`) — `created_at >= week_start` 집계
- [ ] `GET /admin/sales/summary` 응답에 **전월 대비 증감액 + 증감률** 포함
- [ ] `GET /users/me` 응답에 **누적 절약 무게(kg)** 포함 — 배송완료된 OrderItem의 `weight_snapshot` 합산
- [ ] `GET /products/{id}` 응답에 **이미지 라벨별 그룹핑** 또는 라벨 정렬 보장 (정면→측면→내부→흠집→뒷면→제품번호)
- [ ] `POST /favorites/{product_id}` / `DELETE /favorites/{product_id}` — 응답에 `favorite_count` 동시 반환(상세 화면 카운터 갱신용)

### 7.3 검증 / 비즈니스 룰

- [ ] **개인정보 수정 정책** — 필드별 변경 허용 수준 및 구현 상태

  | 필드 | 정책 | 구현 상태 |
  |---|---|---|
  | `password` | 현재 비번 확인 후 변경 | ✅ 완료 |
  | `phone` | SMS 인증코드 발송 → 확인 후 교체 | ✅ **완료** (`/users/me/phone/send-verification`, `/verify` — Redis OTP, mock SMS) |
  | `email` | 새 이메일로 인증코드 발송 → 확인 후 교체 | ❌ 미구현 (`/users/me/email/*` — Redis는 준비됐으나 라우터 없음). 회원가입 단계 이메일 인증(`/auth/email/*`)은 별도로 완료됨 |
  | `username` | Octomo 휴대폰 인증 완료 후 변경 잠금 (현재 자유변경 가능) | ❌ 미구현 — 조건 `phone_verified_at IS NOT NULL` |
  | `login_id` | 변경 불가 | ✅ 변경 불가 유지 |

  - `app/core/redis.py`가 이미 구현되어 이메일 변경 라우터 추가 시 인프라 준비는 끝난 상태 — 남은 건 `/users/me/email/*` 엔드포인트와 서비스 로직뿐
  - `username` 잠금: `phone_verified_at IS NOT NULL`(Octomo 인증 완료) 조건으로 `PATCH /users/me` 에서 차단 (본인인증 PG 폐기로 2026-11-05 조건 갱신)
- [ ] **환불 정책 7일** ([screens-buyer-1.jsx:371](/tmp/rekle-design/extracted2/rekle/project/screens-buyer-1.jsx)): "배송 후 7일 이내 동작 불량은 환불 가능, 단순 변심 반품 불가"
  - `POST /orders/{id}/refund/request`에서 `delivered_at + 7일` 윈도우 검증
  - 사유를 `MALFUNCTION` / `CHANGE_OF_MIND` 구분 — 후자는 자동 거절
- [x] **직접배송 가능 지역**: 주문서에서 `address.zipcode`가 서울/경기일 때만 `DIRECT` 옵션 노출
  - [x] 1차: 정적 zipcode prefix 화이트리스트 `app/core/shipping.py`의 `is_direct_delivery_available()`
  - [ ] 2차: `ProductDirectRegion` 모델로 상품별 가능 지역 다르게 (Phase 3)
- [x] **본인인증 우회 방지**: `POST /orders` 호출 시 `user.verified`(= `phone_verified_at IS NOT NULL`, Octomo) 검증, `IDENTITY_REQUIRED` 에러 반환
- [x] **재고 차감 타이밍**: 주문 생성(PENDING) 시 예약 → 결제 confirm 시 확정 / 취소 시 복구 (요구사항 정의서와 동일)

### 7.4 정적 데이터 / 상수

- [x] ~~`app/catalog/catalog_schemas.py`의 `CATEGORY_META`~~ — DB `product_categories` 로 대체 (`b427d8f8f268`)
- [x] `app/core/shipping.py` — 배송비 상수 + `is_direct_delivery_available()` (zipcode prefix 검증)
  ```python
  FREIGHT_FEE = 60_000        # 화물택배
  DIRECT_FEE = 40_000         # 직접배송
  DIRECT_DISCOUNT = 20_000    # 직배송 할인 (FREIGHT 기준 절감액)
  ```

### 7.5 운영 / 시드

- [ ] 더미 상품 시드 8건 — `design-system.jsx`의 `PRODUCTS`를 그대로 가져와 SQL/Alembic seed로 (브랜드/모델/연식/등급/가격/원가 매칭)
- [ ] 카테고리 아이콘은 프론트 책임이라 백엔드는 `icon` 키만 노출하면 됨

### 7.6 우선순위 재정렬 (Phase 1 추가/조정)

- **Phase 1로 승격**: `Favorite`, `discount_desc` 정렬, `shipping_method` 분기 견적, 직접배송 zip 화이트리스트, 7일 환불 윈도우 검증
- **Phase 2 유지**: `Promotion`, `Notification`, 누적 절약 표시 (단순 합계는 Phase 1에서도 가능)
- **Phase 3 유지**: `ProductInquiry`, `ProductDirectRegion`(상품별 가능 지역), 검색 고도화

---

## 8. 디자인-백엔드 정합성 체크리스트 (구현 후 확인)

- [x] ~~홈 카테고리 그리드 8개와 `ProductCategory` enum + `CATEGORY_META` 매핑이 1:1로 일치~~ — 폐기: 카테고리 DB 관리로 고정 매핑 불필요
- [ ] 상품 카드의 `discountPct`, `won(price)`, 등급 뱃지 색상 — API 응답 `original_price`/`price`/`condition_grade`로 모두 계산 가능
- [ ] 상세 이미지 6 라벨이 모두 노출 가능한 ProductImage 데이터로 채워질 수 있음 (정면 필수, 흠집은 B/C 권장)
- [ ] 장바구니 합계 = 상품금액 + 화물 배송비(60K) - 직배송 할인(20K) — `cart/summary` API와 화면 모두 동일 식
- [ ] 결제 완료 화면의 "신한카드 1234 · 일시불" — `Payment.card_company / card_last4 / installment_months` 응답으로 렌더 가능
- [ ] 마이페이지 4단계 카운트 — `OrderStatus`별 집계 API 1회 호출로 채울 수 있음
- [ ] Admin 주문 표 송장입력 액션 — `결제완료` / `준비중` 상태에서만 노출 (디자인 §A03에서 그렇게 분기됨)

---

## 9. 구현 순서 (Implementation Roadmap)

> **아키텍처**: Modular Monolith + Layered (기본) + Ports & Adapters (외부 통합 모듈만)
> **모듈 위치**: `app/{auth,user,catalog,cart,address,order,payment,common,admin,help}/` — `docs/memory.md` 참고
> **현재 상태 (2026-11-05)**: Week 0~6 대부분 완료 + help 모듈 + 토스 실연동 + 관측성 O0·O1(로깅). 테스트 666개. 미완: shipment추적·알림센터·rate limit·보안 헤더·이메일 변경. (SMS 인증·본인인증 PG·CI/DI 암호화는 폐기)

각 주차 끝에 마이그레이션 1개씩 추가하고, 모든 새 엔드포인트는 통합 테스트(pytest + httpx) 1개씩 동반.

### Week 0 — 인프라 / 공통 기반 ✅ 완료

- [x] `app/core/security.py` — JWT 발급/검증 (`python-jose`), 비번 해시 (`bcrypt`), social signup token
- [x] `app/core/deps.py` — `get_current_user`, `get_current_active_user`, `get_auth_service`, `get_oauth_provider`, `get_email_sender`
- [x] `app/core/pagination.py` — `PageParams`, `CursorParams`, 응답 `meta` 헬퍼
- [x] `app/core/exceptions.py` — `BusinessError` 계층 + 글로벌 Exception 핸들러 (CORS 헤더 포함)
- [x] `tests/conftest.py` — async test client, `make_user` 헬퍼, fake repo 패턴
- [x] `pyproject.toml dev extras` — ruff/mypy/pytest-asyncio 설정 완료
- [ ] `app/core/middleware.py` — 보안 헤더(HSTS/X-Content-Type-Options) → §2 보안 헤더로 통합 (structlog JSON 로깅·request_id 는 2026-11-05 완료)
- [x] `app/core/redis.py` — **신규 완료** `redis-py` async 클라이언트 + `Depends(get_redis)`, 이메일/휴대폰 인증코드 캐시에 사용 중
- [ ] `app/core/rate_limit.py` (→ §2 Rate Limit 으로 통합) — slowapi 기반 (auth류 1분 10회, 일반 60회) — 전역 미적용 (인증코드 발송 자체의 60초 rate-limit은 Redis로 개별 구현됨)

### Week 1 — Auth + User 모듈 ✅ 완료 (일부 잔여)

- [x] `app/auth/{router,service,repository,schemas}.py`
- [x] `POST /auth/sign-up` — `login_id`/비번/이름/이메일, `UsernameTaken`/`EmailTaken` 처리
- [x] `POST /auth/sign-in` — JWT access(body) + refresh(HttpOnly 쿠키), `remember` 분기
- [x] `POST /auth/refresh` — refresh 쿠키로 새 access 발급 (rotation)
- [x] `POST /auth/sign-out` — refresh 쿠키 폐기
- [x] `POST /auth/check-login-id` — 아이디 중복 확인
- [x] `POST /auth/find-id` — 이메일로 아이디 발송 (BackgroundTasks, enumeration 방어)
- [x] `POST /auth/find-password` — 임시 비밀번호 발급 메일 발송 (BackgroundTasks)
- [x] `POST /auth/social/{kakao,naver,google}/callback` — OAuth 어댑터 3종 + 이메일 자동 연결
- [x] `POST /auth/social/sign-up` — tempToken 소셜 신규가입
- [x] `POST /auth/email/send-verification`, `POST /auth/email/verify-code` — **신규 완료** 회원가입 시 이메일 소유 인증(Redis 코드 캐시 + 60초 rate-limit), `verifiedToken`(JWT)을 sign-up 요청에 필수로 사용
- [x] `app/user/{user_router,user_service,user_repository,user_schemas}.py`
- [x] `GET /users/me` — 프로필 + 소셜 연결 현황
- [x] `POST /users/me/password` — 비밀번호 변경 (`must_change_password` 해제)
- [x] ~~`POST /auth/sms/send`, `POST /auth/sms/verify`~~ — 폐기: **2026-11-05 결정: SMS 인증 안 함** — 휴대폰 인증은 Octomo(`/users/me/phone/*`)로 일원화
- [x] `POST /users/me/phone/send-verification`, `POST /users/me/phone/verify` — **완료** 전화번호 변경용 Octomo 인증
- [x] `PATCH /users/me` — username/phone 부분 업데이트
  - ⚠️ **TODO**: `username` 변경 잠금 — Octomo 휴대폰 인증(`phone_verified_at`) 완료 후에는 PATCH 로 자유 변경 불가로 바꿔야 함. 현재는 인증 없이 변경 가능 (본인인증 PG 는 폐기 — §7.3 개인정보 수정 정책과 같은 항목)
- [x] `DELETE /users/me` — PII 전체 익명화 + `UserStatus.WITHDRAWN` + `withdrawn_at` 기록
- [x] ~~CI/DI 컬럼 양방향 암호화 (AES-GCM)~~ — 폐기: CI/DI 컬럼 삭제(`6105137b8e93`)

### Week 2 — Catalog (상품) 모듈 ✅ 완료 (일부 잔여)

- [x] `app/catalog/{router,service,repository,schemas}.py` + `catalog_utils.py`
- [x] `GET /products` — 필터(category/q/grade/min_price/max_price/warranty) + 정렬 + 페이지네이션
- [x] `GET /products/{id}` — 이미지·스펙·등급 안내·배송정보 통합 응답
- [x] `GET /products/featured` — 홈 "오늘 입고된 상품" 4건
- [x] `GET /categories` — 카테고리 목록 (DB 테이블)
- [ ] `GET /products/popular-keywords` — 검색 페이지 (Redis 집계 캐시, 미구현)
- [x] **시드 데이터**: `scripts/seed.py` 6개 상품
- [x] (Admin) `GET/POST/GET/{id}/PATCH/DELETE /admin/products` — CRUD + ADMIN role guard
- [x] ~~(Admin) `POST /admin/products/{id}/images`~~ — `PUT .../images`(전체 교체)·`PATCH .../images/{image_id}`(단건 수정)로 구현

### Week 3 — Cart + Favorites + Address 모듈 ✅ 완료 (일부 잔여)

- [x] `app/favorites/` 모듈 + 마이그레이션 — `Favorite(user_id, product_id)` composite PK
- [x] `GET /favorites`, `POST/DELETE /favorites/{product_id}` (멱등)
- [x] `app/cart/{router,service,repository,schemas}.py`
- [x] `GET /cart` — items + summary(itemsTotal/shippingFeeEstimate/total)
- [x] `POST /cart/items` — 동일 상품 시 수량 합산 (upsert), 재고 검증
- [x] `PATCH /cart/items/{id}`, `DELETE /cart/items/{id}`, `POST /cart/items/bulk-delete`
- [ ] `POST /cart/sync` — 비로그인→로그인 머지 (미구현)
- [x] `app/address/{router,service,repository,schemas}.py`
- [x] `GET/POST/PATCH/DELETE /addresses` + 기본 배송지 토글
- [x] 직배송 가능 zip 화이트리스트 검증 (`app/core/shipping.py`)

### Week 4 — Order 모듈 ✅ 완료 (일부 잔여)

- [x] `app/order/{router,service,repository,schemas}.py`
- [x] `app/order/order_number.py` — `RK-YYMMDD{id:04d}` 포맷
- [x] `POST /orders/quote` — 배송방식별 견적 (락 없는 read-only), `IDENTITY_REQUIRED` 가드
- [x] `POST /orders` — 본인인증 → 배치 `WHERE id IN (...) FOR UPDATE` → 주문 생성 → 재고 차감
- [x] `GET /orders`, `GET /orders/{order_number}` — 본인 주문만
- [x] `POST /orders/{order_number}/cancel` — PENDING/PAID/PREPARING만, `cancelled_at` 기록
- [x] `POST /orders/{order_number}/refund/request` — DELIVERED → PG 전액 취소 후 REFUNDED (Task 3·4)
- [ ] 주문 생성 동시성 통합 테스트 — 동일 상품 동시 주문 1건만 성공 검증 (미구현)

### Week 5 — Payment 모듈 ✅ 완료 (일부 잔여)

- [x] `app/payment/adapters/toss.py` — `PaymentGateway` Protocol 구현 (TossPaymentGateway)
- [x] `app/core/deps.py`에 `get_payment_service()` — TossPaymentGateway 와이어링
- [x] `POST /payments/init` — 주문 검증(소유자 + PENDING) + Payment(READY) 생성
- [x] `POST /payments/confirm` — Toss confirm + 금액 검증 + Order PAID 전환
- [x] `POST /payments/webhooks/toss` — 수신 후 결제 조회 API 재확인 + 멱등 상태 전환 (토스 결제 웹훅엔 서명 없음)
- [x] ~~`PaymentService.verify_webhook()`~~ — Task 1(`233a264`)에서 제거, 웹훅은 결제 조회 재확인 방식(`handle_webhook`)
- [x] ~~`POST /payments/{id}/cancel`, `POST /payments/{id}/refund`~~ — 설계 변경: 주문 취소·환불요청·관리자 취소 엔드포인트가 `PaymentService.cancel_payment` 호출
- [x] ~~**본인인증 PG**: `toss_identity.py` — `IdentityVerifier`~~ — 폐기: Octomo 휴대폰 인증으로 대체
- [x] ~~`POST /verifications/{start,callback}`~~ — 폐기 (§1.2)

### Week 6 — Shipment + Help + Admin (1.8, 1.9, 1.10~1.13) ✅ 대부분 완료

- [x] `GET /orders/{order_number}/shipment` — 배송 정보 조회
- [ ] `GET /shipments/{tracking_number}/track` — 스마트택배 API 프록시 (미구현, Redis 캐시 5분)
- [x] `app/help/` 모듈 — **신규 완료** 공지/FAQ/문의 (`router.py`+`admin_router.py`+`service.py`+`repository.py`+`models.py`, 마이그레이션 `9855aeca0293`+`f25b27344175`+`0de60b6871de`) — 문의는 로그인 필수, 답변 등록 + 내 문의 조회 포함
- [x] `GET /admin/dashboard/sales-chart` **버그 수정 완료** — `dashboard_service.py`의 `date_trunc()` 호출을 `literal_column`으로 바꿔 SELECT/GROUP BY/ORDER BY 세 곳이 동일 표현식을 공유하도록 수정 (기존엔 매번 별도 bind parameter로 바인딩되어 Postgres `GroupingError` → 500, CORS 헤더 없는 응답으로 위장돼 보였음). 실제 Postgres 대상 통합 테스트(`tests/integration/test_dashboard_service.py`) 추가 — fake repo로는 이런 SQL 구조 버그가 재현되지 않아 최초로 real-DB 통합 테스트 패턴을 도입함
- [ ] `app/notification/` 모듈 — `Notification` 신규 모델 + 알림 목록/읽음 (미구현)
- [x] **Admin 라우터** (모두 `Depends(get_current_admin)` 가드):
  - [x] `/admin/dashboard/{summary,sales-chart,pending-orders,popular-categories,stock-alerts}`
  - [x] `/admin/products` CRUD + 이미지 전체 교체
  - [x] `/admin/orders` 목록/상세/송장입력/상태변경/취소/CSV 내보내기
  - [x] `/admin/members` 목록/상세/검색/상태변경 + KPI 4종
  - [x] `/admin/sales/{summary,timeseries,by-payment-method,top-products,export.csv}`
  - [ ] `/admin/inventory` bulk CSV import (미구현)

### Week 7 — 운영 / 마무리 (필수)

- [ ] **감사 로그** — Hibernate Envers 대용으로 SQLAlchemy `event.listens_for` 또는 `Audited` 패턴 (mutation 1년 보존)
- [ ] **모니터링** — 상단 "관측성 구축" 섹션 O0~O6 으로 상세화 (structlog JSON + Prometheus/Grafana + Sentry)
- [ ] **운영 헤더** (→ §2 보안 헤더 미들웨어로 통합) — `Strict-Transport-Security`, `X-Content-Type-Options: nosniff` 미들웨어
- [ ] **레이트 리밋** 전 라우터 적용 (→ §2 Rate Limit 으로 통합)
- [ ] **PII 양방향 암호화** 검증 — phone/email AES-GCM, 비번 argon2id
- [ ] **백업** — pg_dump 일 1회 + WAL 5분 단위 (infra 작업)
- [ ] **부하 테스트** — 상단 "관측성 구축" 섹션 O7~O8 로 상세화 (k6, 스테이징 전용, 개선 루프)
- [ ] **운영 문서** — `docs/runbook.md` (PG 결제 실패 / 재고 race / webhook 미수신 대응)

### 우선순위 매트릭스 (블로킹 / 긴급)

| 작업 | 블로킹 | 이유 |
|---|---|---|
| Week 0 (security/deps/pagination) | ★★★ | 모든 라우터가 의존 |
| Week 1 (auth) | ★★★ | 거의 모든 비-Public 엔드포인트가 의존 |
| Week 4 (order) | ★★★ | 결제·배송·관리자 매출이 모두 Order 의존 |
| Week 5 (payment) | ★★ | order는 PENDING 상태로 생성 가능, Order 부분 테스트 가능 |
| Week 2 (catalog) | ★★ | cart/order의 stock 검증이 의존 |
| Week 3 (cart/wishlist/address) | ★ | order에 필요하나 mock 가능 |
| Week 6 (admin) | ★ | 운영 단계에서 필요, 사용자 트래픽엔 무영향 |
| Week 7 (운영) | — | 출시 직전 검증

---

## 각주 — 결제 개선 항목 (Phase 2 후보)

### Payment confirm: `payment_id` 기반 정확한 READY 매칭 (Task 5-1 옵션 a)

현재 `confirm_payment`는 주문 ID로 READY 결제를 찾는데, Task 4 멱등성으로 정상 흐름에서
READY는 항상 최대 1개이므로 실용적으로 문제가 없다.

하지만 사용자가 여러 결제수단을 동시에 시도하는 기능이 생기면 READY가 여러 개가 될 수 있고,
이때 "어느 READY를 confirm할지" 명시해야 한다. 해결책:
- `PaymentConfirmRequest`에 `payment_id: int` 필드 추가 (프론트가 `init_payment` 응답의
  `payment_id`를 들고 있다가 confirm 시 같이 전송)
- `payment_schemas.py` + `payment_router.py` + 프론트 SDK 변경 필요

Phase 2 다중 결제수단 지원 시 재검토 필요.
