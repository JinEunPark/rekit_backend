# Rekle Backend TODO — 디자인 시스템 기반 구현 계획

> **분석 기준**: `/Volumes/A/web_projects/rekle` 프론트 디자인 (Vue 3 mockup, `_design/buyer/*`, `_design/admin/*`)
> **현 백엔드 상태** (2026-06-24 기준):
> - **구현 완료**: auth 전체 / users (PATCH·DELETE /me 포함) / catalog (DB 동적 카테고리) / admin catalog CRUD / admin dashboard·orders·members·sales / cart / favorites / address / order (환불요청·배송조회 포함) / payment (init·confirm·webhook) / uploads
> - **미구현**: SMS 인증 / 본인인증 PG 연동 / shipment 추적 (스마트택배 API) / 알림·공지 / PG 환불 실호출
> - **테스트**: 291개 통과 (단위 + 통합, DB·Redis 없이 fake repo + fake OAuth)
> **작성일**: 2026-05-01 / **최종 업데이트**: 2026-06-24

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
- [ ] `POST /auth/sms/send` — SMS 인증번호 발송 (Redis에 코드 캐시, rate-limit)
- [ ] `POST /auth/sms/verify` — SMS 인증번호 검증 → `phone_verified_at` 기록
- [x] `PATCH /users/me` — 이름/연락처 수정
- [x] `DELETE /users/me` — 회원탈퇴 (CI/DI 즉시 파기, `withdrawn_at` 기록, 거래정보 5년 보존)
- [ ] `POST /users/me/social/connect` — 기가입 사용자 소셜 계정 추가 연결

### 1.2 본인인증 (`/api/v1/verifications`)

- [ ] `POST /verifications/start` — 본인인증 세션 생성 (provider: TOSS/NICE), redirect URL 반환
- [ ] `POST /verifications/callback` — PG 콜백 (멱등성 보장 — request_id 유니크)
- [ ] `GET /verifications/me/status` — 현재 사용자 인증 상태

### 1.3 주소록 (`/api/v1/addresses`) ✅ 구현 완료

- [x] `GET /addresses` — 내 배송지 목록
- [x] `POST /addresses` — 추가
- [x] `PATCH /addresses/{id}` — 수정 (기본 배송지 토글 포함)
- [x] `DELETE /addresses/{id}`

### 1.4 상품 — 구매자 (`/api/v1/products`) ✅ 구현 완료

- [x] `GET /products` — 목록 (query: `category`, `q`(검색), `grade`, `min_price`, `max_price`, `warranty`, `sort`(latest/price_asc/price_desc), `page`)
- [x] `GET /products/{id}` — 상세 (이미지 다중, 스펙, 등급 안내, 배송정보)
- [x] `GET /products/featured` — 홈 "오늘 입고된 상품" 4건 (`order by created_at desc, status=ACTIVE`)
- [x] `GET /categories` — 카테고리 메타(아이콘/라벨 — 정적 응답)

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
- [x] `POST /payments/webhooks/toss` — HMAC 서명 검증 + 멱등 상태 전환
- [x] `POST /orders/{order_number}/refund/request` — 환불 요청 (DELIVERED → REFUNDED 상태 전환. PG 실호출은 미구현)

### 1.8 배송 (`/api/v1/shipments`)

- [x] `GET /orders/{order_number}/shipment` — 배송 정보
- [ ] `GET /shipments/{tracking_number}/track` — 스마트택배 API 프록시 (Redis 캐시)

### 1.9 알림 / 공지 (`/api/v1/notifications`, `/api/v1/announcements`) **[모델 신규]**

- [ ] `GET /notifications` — 내 알림 목록 (벨 아이콘)
- [ ] `POST /notifications/{id}/read`
- [ ] `GET /announcements` — 공지사항 (My 메뉴)
- [ ] `GET /announcements/{id}`

### 1.10 관리자 — 대시보드 (`/api/v1/admin/dashboard`) ✅ 구현 완료

- [x] `GET /admin/dashboard/summary` — KPI 4종(오늘 주문수/매출/처리대기/재고부족), 비교값(전일 대비, 긴급 카운트)
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
- [ ] `POST /admin/products/import-csv` — Phase 우선순위 낮음

### 1.12 관리자 — 주문 (`/api/v1/admin/orders`) ✅ 대부분 구현 완료

- [x] `GET /admin/orders` — 표 (탭: 전체/결제완료/준비중/배송중/배송완료/취소환불, 카운트 포함)
- [x] `GET /admin/orders/{order_number}` — 상세
- [x] `POST /admin/orders/{order_number}/shipment` — 송장 입력 (carrier+tracking_number) → 자동 SHIPPING 상태 전환
- [x] `PATCH /admin/orders/{order_number}/status` — 수동 상태 변경 (배송완료 등)
- [x] `POST /admin/orders/{order_number}/cancel` — 관리자 취소
- [ ] `POST /admin/orders/{order_number}/refund` — PG 부분/전액 취소 호출 (미구현 — PG 연동 필요)
- [x] `GET /admin/orders/export.csv`

### 1.13 관리자 — 회원 (`/api/v1/admin/members`) ✅ 구현 완료

- [x] `GET /admin/members/summary` — KPI 4종(전체/인증/신규/구매)
- [x] `GET /admin/members` — 표 (검색: 이름/이메일/휴대폰)
- [x] `GET /admin/members/{id}` — 상세 (가입일, 주문 이력)
- [x] `PATCH /admin/members/{id}/status` — 활성/제재 토글

### 1.14 관리자 — 매출 (`/api/v1/admin/sales`) ✅ 구현 완료

- [x] `GET /admin/sales/summary?from=&to=` — 헤드라인(총매출/주문수/평균주문/취소율, 전월 대비)
- [x] `GET /admin/sales/timeseries?from=&to=&granularity=day|week`
- [x] `GET /admin/sales/by-payment-method?from=&to=`
- [x] `GET /admin/sales/top-products?from=&to=&limit=5`
- [x] `GET /admin/sales/export.csv`

### 1.15 업로드 ✅ 구현 완료

- [x] `POST /uploads/presign`
- [x] `POST /uploads/confirm`
- [ ] **추가 검토**: `purpose`를 `product_image` 외 `verification_doc` 등으로 확장

---

## 2. 인프라 / 공통 작업

- [x] **JWT 인증 의존성** (`Depends(get_current_user)`, `Depends(get_current_active_user)`) — `app/core/security.py` + `app/core/deps.py` 완료
- [x] **에러 응답 표준화** — `{code, message}` 포맷 + 글로벌 Exception 핸들러 (500도 CORS 헤더 부착)
- [x] **CORS** — `settings.cors_origins` 설정 완료, 글로벌 에러도 CORS 헤더 부착
- [x] **Pydantic 스키마** — auth/user 도메인 완료 (`app/auth/auth_schemas.py`, `app/user/user_schemas.py`)
- [x] **BackgroundTasks** — 이메일 발송 분리 (SMTP 지연이 요청 트랜잭션 묶지 않음)
- [x] **이메일 어댑터** — `ConsoleEmailSender` (개발) + `GmailSmtpEmailSender` (운영) Protocol 기반
- [x] **OAuth 어댑터** — 카카오/네이버/구글 `httpx` 기반 + `translate_oauth_error` 헬퍼 (Ports & Adapters)
- [x] **테스트** — 단위 131개 (DB 없이 fake repo + fake OAuth), `tests/conftest.py` 기반
- [x] **CRUD 레이어** — catalog/cart/address/order/payment/favorites/admin_catalog 완료
- [x] **`order_number` 생성기** — `RK-YYMMDD{id:04d}` 포맷, `app/order/order_number.py`
- [ ] **CI/DI 암호화 유틸** — KMS or Fernet, `services/crypto.py`
- [ ] **외부 연동 서비스 모듈**
  - [ ] `services/sms.py` — NHN Cloud / 알리고
  - [x] `app/payment/adapters/toss.py` — 결제 confirm/webhook 검증 (TossPaymentGateway)
  - [ ] `services/toss_identity.py` 또는 `services/nice_identity.py`
  - [ ] `services/sweet_tracker.py` — 배송 추적 (Redis 캐시 5분)
- [x] ~~`services/social_oauth.py`~~ — 어댑터 패턴으로 `app/auth/adapters/` 에 구현 완료
- [ ] **Redis 통합** — `core/redis.py` (SMS 코드, 비로그인 장바구니, 배송 캐시, rate limit) — 의존성 있음, 미구현
- [ ] **Rate Limit** — `slowapi` 의존성 있음, 미적용 (auth류 1분 10회, 일반 60회)
- [ ] **관리자 보안** — IP 화이트리스트 또는 2FA, OpenAPI 문서 prod 비공개 (이미 적용됨)
- [ ] **통합 테스트** — testcontainers + pytest-asyncio (DB 쿼리 정확성·트랜잭션·인증 가드 검증)

---

## 3. 데이터/시드

- [x] 카테고리 메타 응답 (정적): `GET /categories` — `app/catalog/catalog_schemas.py`의 `CATEGORY_META`
- [x] 관리자 계정 부트스트랩 스크립트 — `scripts/seed.py` (재실행 안전, admin01/hong001/kim001)
- [x] 더미 상품 시드 (개발 편의) — `scripts/seed.py` 6개 상품 포함
- [x] E2E 스모크 테스트 스크립트 — `scripts/test_api.sh` 33케이스 (멱등)

---

## 4. 우선순위 (요구사항정의서 Phase에 정렬)

### Phase 1 (최소 동작)

1. ✅ JWT/Depends 정비 + auth (sign-up/sign-in/refresh/sign-out/find-id/find-password/소셜 3종)
2. ✅ GET /users/me, POST /users/me/password, PATCH /users/me, DELETE /users/me
3. ✅ 상품 조회 (buyer) — `GET /products`, `GET /products/{id}`, `GET /products/featured`, `GET /categories`
4. ✅ 주소록 CRUD
5. ✅ 장바구니 CRUD + 관심상품 CRUD
6. 본인인증 PG 연동 (start/callback/me) — Order 진입 가드 **(DB 직접 설정으로 우회 중)**
7. ✅ 주문 생성 + 토스 결제 confirm/webhook (멱등) + 환불 요청 + 배송 정보 조회
8. ✅ 관리자 상품 CRUD + 이미지 관리 + 주문 관리(송장·상태·취소·CSV) + 대시보드 + 회원 + 매출

### Phase 2 (안정화)

9. 배송 추적 자동 폴링 (Celery / 스마트택배 API)
10. PG 환불 실호출 (`POST /admin/orders/{n}/refund`, `POST /payments/{id}/refund`)
11. SMS/이메일 알림 발송
12. 알림센터 (`Notification` 모델 + 목록/읽음)

### Phase 3 (확장)

14. 후기 (리뷰), 직접배송 지역 관리, 검색 고도화, 다중 판매자

---

## 5. 모델 변경 평가 — `세부 내용은 §6` 참조 (요약)

| 모델 | 변경 필요 | 우선순위 |
|---|---|---|
| `Product` | 디자인 태그(인기/신규입고/베스트), 노출 정렬 — **선택** | 중 |
| `ProductImage` | `label`(정면/측면/...) 컬럼 추가 — **권장** | 중 |
| `User` | `status` enum(`ACTIVE`/`BANNED`) 추가 — **권장** (관리자 회원관리 표 "활성/제재") | 중 |
| `Order` | `discount_amount`, `shipping_method` 추가 — **필수** (직배송 할인 -20k) | 상 |
| `Order` | 주문 생성 시 배송지 스냅샷에 `recipient`만 있고 가입자명 별도 필요시 — **현행 OK** | — |
| `OrderItem` | `product_image_url_snapshot` — **권장** (목록에서 이미지 노출) | 중 |
| `Payment` | `card_company`, `card_last4`, `installment_months`, `approval_number` — **필수** (Complete 화면 "신한카드 1234 · 일시불") | 상 |
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

### 6.2 `ProductCategory` enum — 8개로 확장 검토

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

- [ ] `ProductCategory` enum에 `VACUUM`, `SMALL_APPLIANCE` 추가 (§6.2)
- [ ] `Product` — `tag`, `featured_until`, `view_count`, `favorite_count`, `sold_count` 추가 (§6.1)
- [ ] `ProductImage` — `label`을 `ProductImageLabel` enum으로 전환, `Product.thumbnail_image_id` FK 또는 `is_primary` 추가 (§6.3)
- [ ] `User` — `status: UserStatus(ACTIVE/BANNED/DORMANT)` 추가, 기존 `is_active`와 정합성 정리 (§6.4)
- [ ] `Order` — `shipping_method: ShippingMethod`, `discount_amount`, `delivery_memo`, `identity_verified_snapshot_name` 추가 (§6.5)
- [ ] `Payment` — `card_company`, `card_last4`, `installment_months`, `approval_number` 추가 (§6.6)
- [ ] `Shipment` — `estimated_delivery_from`, `estimated_delivery_to`, `direct_delivery_note` 추가 (§6.8)
- [ ] **신규** `Favorite(user_id, product_id)` — composite PK (§6.9)
- [ ] **신규** `Promotion` (선택, 정적 JSON 대체 가능) (§6.10)
- [ ] Alembic 마이그레이션 1개로 묶거나, 도메인별로 3~4개로 분할
  - **마이그레이션 분할 권장**: `0002_categories_and_tags`, `0003_favorites`, `0004_order_shipping_payment_fields`

### 7.2 API 보강

- [ ] `GET /products` 정렬 옵션에 **`discount_desc`** 추가 — 기존 latest/price_asc/price_desc에 한 항목 늘림 (§6.1)
- [ ] `GET /products/featured` — 응답에 `tag` 노출 + `featured_until` 필터 적용
- [ ] `POST /orders/quote` — `shipping_method` 인자에 따라 `shipping_fee`/`discount_amount` 계산
  - 화물택배: 60,000원
  - 직접배송: 40,000원, 직배송 가능 지역(서울/경기) 외엔 선택 불가
  - 일반택배: 무게/사이즈 기반 (작은 가전 한정)
- [ ] `POST /orders` 응답 `order_number` 포맷 확정 — `RK-YYMMDD####` (요구사항정의서/디자인 모두 일치)
- [ ] `GET /admin/dashboard/summary` 응답 필드 — KPI 4종에 **비교값 텍스트(`+3건`, `+18%`, `긴급 2`, `품절 임박`)** 포함
- [ ] `GET /admin/orders` 응답에 **상태별 카운트** 동시 반환 (전체/결제완료/준비중/배송중/배송완료/취소·환불) — 탭 헤더에 표기
- [ ] `GET /admin/members/summary` 응답에 **신규(이번주)** 카운트 포함 — `created_at >= week_start` 집계
- [ ] `GET /admin/sales/summary` 응답에 **전월 대비 증감액 + 증감률** 포함
- [ ] `GET /users/me` 응답에 **누적 절약 무게(kg)** 포함 — 배송완료된 OrderItem의 `weight_snapshot` 합산
- [ ] `GET /products/{id}` 응답에 **이미지 라벨별 그룹핑** 또는 라벨 정렬 보장 (정면→측면→내부→흠집→뒷면→제품번호)
- [ ] `POST /favorites/{product_id}` / `DELETE /favorites/{product_id}` — 응답에 `favorite_count` 동시 반환(상세 화면 카운터 갱신용)

### 7.3 검증 / 비즈니스 룰

- [ ] **환불 정책 7일** ([screens-buyer-1.jsx:371](/tmp/rekle-design/extracted2/rekle/project/screens-buyer-1.jsx)): "배송 후 7일 이내 동작 불량은 환불 가능, 단순 변심 반품 불가"
  - `POST /orders/{id}/refund/request`에서 `delivered_at + 7일` 윈도우 검증
  - 사유를 `MALFUNCTION` / `CHANGE_OF_MIND` 구분 — 후자는 자동 거절
- [x] **직접배송 가능 지역**: 주문서에서 `address.zipcode`가 서울/경기일 때만 `DIRECT` 옵션 노출
  - [x] 1차: 정적 zipcode prefix 화이트리스트 `app/core/shipping.py`의 `is_direct_delivery_available()`
  - [ ] 2차: `ProductDirectRegion` 모델로 상품별 가능 지역 다르게 (Phase 3)
- [x] **본인인증 우회 방지**: `POST /orders` 호출 시 `user.identity_verified_at IS NOT NULL` 검증, `IDENTITY_REQUIRED` 에러 반환
- [ ] **재고 차감 타이밍**: 주문 생성(PENDING) 시 예약 → 결제 confirm 시 확정 / 취소 시 복구 (요구사항 정의서와 동일)

### 7.4 정적 데이터 / 상수

- [x] `app/catalog/catalog_schemas.py`의 `CATEGORY_META` — 카테고리 메타 dict (id, label_ko, icon_key, sort_order)
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

- [ ] 홈 카테고리 그리드 8개와 `ProductCategory` enum + `CATEGORY_META` 매핑이 1:1로 일치
- [ ] 상품 카드의 `discountPct`, `won(price)`, 등급 뱃지 색상 — API 응답 `original_price`/`price`/`condition_grade`로 모두 계산 가능
- [ ] 상세 이미지 6 라벨이 모두 노출 가능한 ProductImage 데이터로 채워질 수 있음 (정면 필수, 흠집은 B/C 권장)
- [ ] 장바구니 합계 = 상품금액 + 화물 배송비(60K) - 직배송 할인(20K) — `cart/summary` API와 화면 모두 동일 식
- [ ] 결제 완료 화면의 "신한카드 1234 · 일시불" — `Payment.card_company / card_last4 / installment_months` 응답으로 렌더 가능
- [ ] 마이페이지 4단계 카운트 — `OrderStatus`별 집계 API 1회 호출로 채울 수 있음
- [ ] Admin 주문 표 송장입력 액션 — `결제완료` / `준비중` 상태에서만 노출 (디자인 §A03에서 그렇게 분기됨)

---

## 9. 구현 순서 (Implementation Roadmap)

> **아키텍처**: Modular Monolith + Layered (기본) + Ports & Adapters (외부 통합 모듈만)
> **모듈 위치**: `app/{auth,user,catalog,cart,address,order,payment,common}/` — `docs/memory.md` 참고
> **현재 상태 (2026-06-24)**: Week 0~6 대부분 완료. 테스트 291개. 미완: SMS/본인인증 PG/PG환불실호출/shipment추적/알림.

각 주차 끝에 마이그레이션 1개씩 추가하고, 모든 새 엔드포인트는 통합 테스트(pytest + httpx) 1개씩 동반.

### Week 0 — 인프라 / 공통 기반 ✅ 완료

- [x] `app/core/security.py` — JWT 발급/검증 (`python-jose`), 비번 해시 (`bcrypt`), social signup token
- [x] `app/core/deps.py` — `get_current_user`, `get_current_active_user`, `get_auth_service`, `get_oauth_provider`, `get_email_sender`
- [x] `app/core/pagination.py` — `PageParams`, `CursorParams`, 응답 `meta` 헬퍼
- [x] `app/core/exceptions.py` — `BusinessError` 계층 + 글로벌 Exception 핸들러 (CORS 헤더 포함)
- [x] `tests/conftest.py` — async test client, `make_user` 헬퍼, fake repo 패턴
- [x] `pyproject.toml dev extras` — ruff/mypy/pytest-asyncio 설정 완료
- [ ] `app/core/middleware.py` — 보안 헤더(HSTS/X-Content-Type-Options), structlog JSON 로깅
- [ ] `app/core/redis.py` — `redis-py` async 클라이언트 + `Depends(get_redis)`
- [ ] `app/core/rate_limit.py` — slowapi 기반 (auth류 1분 10회, 일반 60회)

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
- [x] `app/user/{router,service,repository,schemas}.py`
- [x] `GET /users/me` — 프로필 + 소셜 연결 현황
- [x] `POST /users/me/password` — 비밀번호 변경 (`must_change_password` 해제)
- [ ] `POST /auth/sms/send`, `POST /auth/sms/verify` — Redis 코드 캐시 (미구현, Redis 필요)
- [x] `PATCH /users/me` — username/phone 부분 업데이트
- [x] `DELETE /users/me` — CI/DI 파기 + `withdrawn_at` 기록
- [ ] CI/DI 컬럼 양방향 암호화 (AES-GCM) — 미구현

### Week 2 — Catalog (상품) 모듈 ✅ 완료 (일부 잔여)

- [x] `app/catalog/{router,service,repository,schemas}.py` + `catalog_utils.py`
- [x] `GET /products` — 필터(category/q/grade/min_price/max_price/warranty) + 정렬 + 페이지네이션
- [x] `GET /products/{id}` — 이미지·스펙·등급 안내·배송정보 통합 응답
- [x] `GET /products/featured` — 홈 "오늘 입고된 상품" 4건
- [x] `GET /categories` — 카테고리 메타 (정적 dict)
- [ ] `GET /products/popular-keywords` — 검색 페이지 (Redis 집계 캐시, 미구현)
- [x] **시드 데이터**: `scripts/seed.py` 6개 상품
- [x] (Admin) `GET/POST/GET/{id}/PATCH/DELETE /admin/products` — CRUD + ADMIN role guard
- [ ] (Admin) `POST /admin/products/{id}/images` — 이미지 추가/순서 변경 (미구현)

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
- [x] `POST /orders/{order_number}/refund/request` — DELIVERED → REFUNDED 전환 (PG 실호출은 미구현)
- [ ] 주문 생성 동시성 통합 테스트 — 동일 상품 동시 주문 1건만 성공 검증 (미구현)

### Week 5 — Payment 모듈 ✅ 완료 (일부 잔여)

- [x] `app/payment/adapters/toss.py` — `PaymentGateway` Protocol 구현 (TossPaymentGateway)
- [x] `app/core/deps.py`에 `get_payment_service()` — TossPaymentGateway 와이어링
- [x] `POST /payments/init` — 주문 검증(소유자 + PENDING) + Payment(READY) 생성
- [x] `POST /payments/confirm` — Toss confirm + 금액 검증 + Order PAID 전환
- [x] `POST /payments/webhooks/toss` — HMAC 서명 검증 + 멱등 상태 전환
- [x] `PaymentService.verify_webhook()` — router가 _gateway에 직접 접근 안 함
- [ ] `POST /payments/{id}/cancel`, `POST /payments/{id}/refund` (미구현)
- [ ] **본인인증 PG**: `app/auth/adapters/toss_identity.py` — `IdentityVerifier` 구현 (미구현)
- [ ] `POST /verifications/{start,callback}` — 콜백 멱등성 (미구현)

### Week 6 — Shipment + Help + Admin (1.8, 1.9, 1.10~1.13) ✅ 대부분 완료

- [x] `GET /orders/{order_number}/shipment` — 배송 정보 조회
- [ ] `GET /shipments/{tracking_number}/track` — 스마트택배 API 프록시 (미구현, Redis 캐시 5분)
- [ ] `app/help/` 모듈 — 공지/FAQ/문의 (미구현)
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
- [ ] **모니터링** — Sentry SDK + structlog JSON 포맷 + Datadog 또는 Grafana 메트릭
- [ ] **운영 헤더** — `Strict-Transport-Security`, `X-Content-Type-Options: nosniff` 미들웨어
- [ ] **레이트 리밋** 전 라우터 적용 (auth류 / 일반 / admin)
- [ ] **PII 양방향 암호화** 검증 — phone/email AES-GCM, 비번 argon2id
- [ ] **백업** — pg_dump 일 1회 + WAL 5분 단위 (infra 작업)
- [ ] **부하 테스트** — k6 또는 locust로 P95 read 200ms / write 500ms 검증
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
