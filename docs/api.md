# Rekit Backend API 요구사항

> Rekit 클라이언트(Vue 3 + Pinia + Vue Router)가 사용할 백엔드 API의 종합 요구사항 문서.
> 현재 프론트엔드는 mock(localStorage·하드코딩 데이터)으로 동작하며, 이 문서의 엔드포인트로 모든 mock을 대체합니다.

- **버전**: v1 (2026-05)
- **작성 기준**: 현재 구현된 모든 화면 (홈, 상품, 카트, 체크아웃 3단계, 마이페이지, 인증 6종, 검색, 정적 페이지)
- **대상**: 백엔드 엔지니어 / API 설계자

---

## 1. 공통 사항

### 1.1 기본 정보

| 항목 | 값 |
|---|---|
| Base URL (production) | `https://api.rekit.kr/v1` |
| Base URL (staging) | `https://api-stg.rekit.kr/v1` |
| Content-Type | `application/json; charset=utf-8` |
| 시간대 | 모든 datetime은 UTC ISO-8601 (`2026-05-01T03:24:00Z`) |
| 인코딩 | URL 파라미터는 RFC 3986 |

### 1.2 인증

```
Authorization: Bearer <accessToken>
```

- **Access Token**: JWT, 만료 30분, 헤더 전송
- **Refresh Token**: HttpOnly + Secure 쿠키, 만료 14일, `/auth/refresh`에서만 사용
- 비로그인 상태에서도 호출 가능한 endpoint는 표에 **Public** 으로 표시
- 로그인이 필요한 endpoint를 비로그인으로 호출하면 **401 Unauthorized**

### 1.3 응답 포맷

성공:
```json
{
  "data": { ... } | [ ... ],
  "meta": { "page": 1, "size": 20, "total": 124 }   // 페이지네이션 시
}
```

실패:
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "휴대폰 번호 형식이 올바르지 않습니다",
    "fields": { "phone": "INVALID_FORMAT" }   // 선택적
  }
}
```

### 1.4 HTTP 상태 코드

| Code | 의미 | 사용 예 |
|---|---|---|
| 200 | OK | 일반 성공 |
| 201 | Created | 리소스 생성 (주문, 회원가입) |
| 204 | No Content | 삭제 성공 |
| 400 | Bad Request | 요청 파싱 실패 |
| 401 | Unauthorized | 토큰 누락/만료/위조 |
| 403 | Forbidden | 본인 리소스가 아닌 자원 접근 |
| 404 | Not Found | 존재하지 않는 리소스 |
| 409 | Conflict | 아이디 중복 등 |
| 422 | Unprocessable | 비즈니스 검증 실패 |
| 429 | Too Many Requests | 레이트 리밋 |
| 500 | Server Error | 서버 내부 오류 |

### 1.5 비즈니스 에러 코드

| Code | HTTP | 의미 |
|---|---|---|
| `INVALID_CREDENTIALS` | 401 | 아이디/비밀번호 불일치 |
| `TOKEN_EXPIRED` | 401 | 액세스 토큰 만료 |
| `USERNAME_TAKEN` | 409 | 아이디 중복 |
| `EMAIL_TAKEN` | 409 | 이메일 중복 |
| `IDENTITY_REQUIRED` | 422 | 본인인증 필요 |
| `OUT_OF_STOCK` | 422 | 재고 부족 |
| `PRICE_CHANGED` | 422 | 카트 → 주문 사이 가격 변동 |
| `PAYMENT_FAILED` | 422 | PG 결제 실패 |
| `OTP_INVALID` | 422 | OTP 불일치/만료 |
| `OTP_RATE_LIMITED` | 429 | OTP 발송 한도 초과 |
| `RATE_LIMITED` | 429 | API 호출 한도 초과 |

### 1.6 페이지네이션

쿼리: `?page=1&size=20` (기본 20, 최대 100)
응답 `meta`: `page`, `size`, `total`, `totalPages`

대안: 커서 기반 (`?cursor=xxx&limit=20`) — 무한 스크롤 페이지에서 사용 권장

### 1.7 정렬

쿼리: `?sort=createdAt:desc` 또는 도메인별 enum (`?sort=price-asc`)

### 1.8 CORS · 보안

- CORS Origin: `https://rekit.kr`, `https://www.rekit.kr`, 개발은 `http://localhost:*`
- `Strict-Transport-Security: max-age=63072000`
- `X-Content-Type-Options: nosniff`
- 모든 mutation(POST/PATCH/DELETE)은 **CSRF 토큰 또는 SameSite=Strict 쿠키 + Authorization 헤더** 조합으로 보호
- 레이트 리밋: IP+사용자별 (예: 인증류 1분당 10회, 일반 60회)

---

## 2. 도메인별 엔드포인트 요약

| 도메인 | 엔드포인트 수 | 비고 |
|---|---|---|
| Auth | 11 | 회원가입·로그인·찾기·본인인증 |
| User | 4 | 내 정보 |
| Products | 5 | 목록·상세·관련·카테고리·인기 검색어 |
| Wishlist | 3 | 관심상품 |
| Cart | 6 | 장바구니 (인증 사용자 동기화) |
| Addresses | 5 | 배송지 CRUD |
| Orders | 6 | 주문·취소·환불·배송조회 |
| Payments | 5 | PG 연동 (대부분 서버↔PG) |
| Help | 4 | 공지·FAQ·문의 |
| Misc | 1 | 우편번호 검색 (외부 SDK 권장) |
| **합계** | **50** | |

---

## 3. Auth — 인증

### 3.1 아이디 중복 확인

```
POST /auth/check-username
```

**Public** · 회원가입 화면의 [중복확인] 버튼

**Body**
```json
{ "username": "eunyoung_kim" }
```

**Response 200**
```json
{ "data": { "available": true } }
```

**Errors**: `USERNAME_TAKEN` (409)

### 3.2 회원가입

```
POST /auth/sign-up
```

**Public**

**Body**
```json
{
  "username": "eunyoung_kim",
  "password": "abc12345",
  "email": "eunyoung@example.com",
  "agreedTerms": true,
  "agreedPrivacy": true,
  "agreedMarketing": false
}
```

검증:
- `username`: `^[a-zA-Z0-9_]{4,20}$`
- `password`: 8자 이상, 영문+숫자 포함 (해시는 서버에서 bcrypt/argon2)
- `email`: RFC 5322
- `agreedTerms`, `agreedPrivacy` 반드시 `true`

**Response 201**
```json
{
  "data": {
    "user": { ...User },
    "accessToken": "eyJ..."
  }
}
```
(Refresh Token은 Set-Cookie로 내려감)

### 3.3 로그인

```
POST /auth/sign-in
```

**Public**

**Body**
```json
{ "username": "eunyoung_kim", "password": "abc12345", "remember": true }
```

`remember`: true면 refresh token 만료 30일, false면 14일

**Response 200**: 회원가입과 동일

**Errors**: `INVALID_CREDENTIALS` (401)

### 3.4 로그아웃

```
POST /auth/sign-out
```

**Auth required**

서버 측 refresh token 무효화 + Set-Cookie로 빈 쿠키 전송. 클라이언트는 access token도 즉시 폐기.

**Response 204**

### 3.5 토큰 재발급

```
POST /auth/refresh
```

**Public** (단, refresh token 쿠키 필요)

**Response 200**
```json
{ "data": { "accessToken": "eyJ..." } }
```

### 3.6 소셜 로그인 콜백 (예약)

```
POST /auth/social/{provider}/callback
```

`provider`: `kakao` | `naver`

**Body**
```json
{ "code": "...", "state": "..." }
```

**Response 200**: 로그인과 동일 + 가입이 필요하면 `needsSignUp: true` 와 `tempToken` 반환

### 3.7 아이디 찾기

```
POST /auth/find-id
```

**Public**

**Body**
```json
{ "email": "eunyoung@example.com" }
```

**Response 200**
```json
{
  "data": {
    "username": "eunyou***kim",   // 마스킹된 형태
    "joinedAt": "2026-04-10"
  }
}
```

이메일에 매칭되는 계정 없으면 보안상 동일 응답 형식으로 빈 결과 (`username: null`) 또는 일부러 동일 메시지 반환 — 응답에서 계정 존재 여부 추론 불가하도록 설계 권장.

### 3.8 비밀번호 재설정 링크 발송

```
POST /auth/find-password
```

**Public**

**Body**
```json
{ "username": "eunyoung_kim", "email": "eunyoung@example.com" }
```

**Response 200**
```json
{ "data": { "sent": true, "maskedEmail": "eu***@example.com" } }
```

이메일로 재설정 토큰 (1회용, 30분 만료) 포함된 링크 발송: `https://rekit.kr/auth/reset-password?token=...`

### 3.9 비밀번호 재설정

```
POST /auth/reset-password
```

**Public**

**Body**
```json
{ "token": "...", "newPassword": "new12345" }
```

**Response 204**

**Errors**: `OTP_INVALID` (token 만료/사용됨)

### 3.10 본인인증 OTP 발송

```
POST /auth/identity/verify-request
```

**Auth required** · 첫 결제 전 1회

**Body**
```json
{ "phone": "010-1234-5678" }
```

**Response 200**
```json
{
  "data": {
    "verifyToken": "vrf_abc123",   // OTP confirm 시 함께 보내야 함
    "expiresIn": 180                // 초
  }
}
```

**Errors**: `OTP_RATE_LIMITED` (429)

### 3.11 본인인증 OTP 확인

```
POST /auth/identity/verify-confirm
```

**Auth required**

**Body**
```json
{ "verifyToken": "vrf_abc123", "code": "284513" }
```

**Response 200**
```json
{
  "data": {
    "user": { ...User, "verified": true, "phone": "010-1234-5678" }
  }
}
```

**Errors**: `OTP_INVALID` (422)

> 실제 운영에서는 토스페이먼츠/NICE/KCP의 본인인증 SDK가 통신사 인증을 처리하고, rekit 서버는 PG가 발급한 인증 결과(CI/DI)만 받아 저장합니다. 자체 OTP 발송은 **개발 mock 단계**에서만 사용하고, production은 PG 연동 권장.

---

## 4. User — 내 정보

### 4.1 내 프로필 조회

```
GET /users/me
```

**Auth required**

**Response 200**
```json
{
  "data": {
    "id": "u_abc123",
    "username": "eunyoung_kim",
    "name": "박은영",
    "email": "eunyoung@example.com",
    "phone": "010-1234-5678",
    "verified": true,
    "ecoKg": 86,
    "createdAt": "2026-04-10T08:30:00Z",
    "marketingOptIn": false
  }
}
```

### 4.2 프로필 수정

```
PATCH /users/me
```

**Auth required**

**Body** (변경할 필드만)
```json
{ "name": "박은영", "email": "new@example.com" }
```

이메일 변경 시 인증 메일 발송 등 재인증 정책 결정 필요.

**Response 200**: 갱신된 user

### 4.3 비밀번호 변경

```
POST /users/me/password
```

**Auth required**

**Body**
```json
{ "currentPassword": "abc12345", "newPassword": "new67890" }
```

**Response 204**

**Errors**: `INVALID_CREDENTIALS` (401)

### 4.4 회원탈퇴

```
DELETE /users/me
```

**Auth required**

**Body** (재인증)
```json
{ "password": "abc12345", "reason": "기타" }
```

탈퇴 후 처리 정책:
- 본인 식별 정보 즉시 익명화
- 주문/결제 기록은 전자상거래법 준수 위해 5년 보존 (사용자 ID는 익명 ID로 치환)

**Response 204**

---

## 5. Products — 상품

### 5.1 상품 목록

```
GET /products
```

**Public**

**Query**
| 파라미터 | 타입 | 설명 |
|---|---|---|
| `cat` | string | 카테고리 slug (`fridge`, `washer`, `tv`, `aircon`, `kitchen`, `cleaner`) |
| `sort` | enum | `newest` (default), `price-asc`, `price-desc`, `discount` |
| `grade` | string | 콤마 구분 (`A`, `A,B`, `B,C` 등) |
| `warranty` | `1` | 동작보증만 |
| `q` | string | 검색어 (title/brand/model 부분 일치) |
| `page` | int | 기본 1 |
| `size` | int | 기본 20, 최대 100 |

**Response 200**
```json
{
  "data": [ ...Product[] ],
  "meta": { "page": 1, "size": 20, "total": 24, "totalPages": 2 }
}
```

### 5.2 상품 상세

```
GET /products/{id}
```

**Public**

**Response 200**
```json
{
  "data": {
    "id": "p1",
    "title": "삼성 양문형 냉장고 384L",
    "brand": "삼성",
    "model": "RT38K5982SL",
    "year": "2021년식",
    "kind": "fridge",
    "category": "냉장고",
    "tone": "mint",
    "grade": "A",
    "price": 180000,
    "originalPrice": 1290000,
    "warranty": true,
    "stock": 1,
    "tag": "동작보증",
    "images": [
      { "label": "정면", "url": "https://cdn.rekit.kr/..." },
      ...
    ],
    "specs": {
      "용량": "384L",
      "크기": "595×668×1715mm",
      "무게": "약 76kg",
      ...
    },
    "createdAt": "2026-05-01T00:00:00Z"
  }
}
```

### 5.3 관련 상품

```
GET /products/{id}/related
```

**Public**

**Query**: `limit` (기본 4)

**Response 200**: `Product[]` (같은 kind, 다른 id, 재고 있음)

### 5.4 카테고리 목록

```
GET /products/categories
```

**Public**

**Response 200**
```json
{
  "data": [
    { "slug": "fridge", "label": "냉장고", "count": 6 },
    { "slug": "washer", "label": "세탁기", "count": 3 },
    ...
  ]
}
```

`count`는 캐시해도 좋음 (10분).

### 5.5 인기 검색어

```
GET /products/popular-keywords
```

**Public** · 검색 페이지의 "인기 검색어"

**Query**: `limit` (기본 8)

**Response 200**
```json
{
  "data": [
    { "rank": 1, "keyword": "삼성 냉장고", "trend": "up" },
    { "rank": 2, "keyword": "LG 트롬", "trend": "same" },
    ...
  ],
  "meta": { "updatedAt": "2026-05-01T00:00:00Z" }
}
```

집계 주기: 1시간 또는 일별 (분석 파이프라인 결과를 캐시).

---

## 6. Wishlist — 관심상품

### 6.1 내 관심상품 목록

```
GET /wishlist
```

**Auth required**

**Response 200**
```json
{
  "data": [
    { "productId": "p1", "addedAt": "2026-05-01T03:00:00Z", "product": { ...Product } },
    ...
  ]
}
```

`product`는 join으로 함께 응답 (N+1 방지).

### 6.2 관심상품 추가

```
POST /wishlist/{productId}
```

**Auth required**

**Response 201** (이미 있으면 200, 멱등성)

### 6.3 관심상품 제거

```
DELETE /wishlist/{productId}
```

**Auth required**

**Response 204**

> 비로그인 사용자: 클라이언트 localStorage에 보관 → 로그인 시 일괄 동기화 (`POST /wishlist/sync` 별도 추가 가능).

---

## 7. Cart — 장바구니

> 비로그인 사용자도 카트 사용 가능. 클라이언트는 localStorage로 보관.
> 로그인 시 서버 카트와 병합 (수량 합치기 또는 큰 값 우선 등 정책 결정 필요).

### 7.1 카트 조회

```
GET /cart
```

**Auth required**

**Response 200**
```json
{
  "data": {
    "items": [
      { "productId": "p1", "qty": 1, "selected": true, "product": { ...Product } }
    ],
    "summary": {
      "itemsTotal": 180000,
      "selectedTotal": 180000,
      "shippingFee": 40000,
      "estimatedTotal": 220000
    }
  }
}
```

### 7.2 카트 아이템 추가

```
POST /cart/items
```

**Auth required**

**Body**
```json
{ "productId": "p1", "qty": 1 }
```

이미 있으면 qty 합산. 재고 초과 시 `OUT_OF_STOCK`.

**Response 200**: 갱신된 cart

### 7.3 카트 아이템 수정

```
PATCH /cart/items/{productId}
```

**Auth required**

**Body** (변경할 필드만)
```json
{ "qty": 2, "selected": false }
```

**Response 200**

### 7.4 카트 아이템 단건 삭제

```
DELETE /cart/items/{productId}
```

**Auth required** · **204**

### 7.5 선택 아이템 일괄 삭제

```
DELETE /cart/items?selected=true
```

**Auth required** · **204**

### 7.6 카트 비우기

```
DELETE /cart
```

**Auth required** · **204** · (주문 완료 후 결제된 아이템만 삭제는 7.5 사용)

### 7.7 카트 동기화 (옵션)

```
POST /cart/sync
```

**Auth required** · 비로그인→로그인 전환 시 클라이언트 카트 병합

**Body**
```json
{ "items": [{ "productId": "p1", "qty": 1 }, ...] }
```

**Response 200**: 병합된 cart

---

## 8. Addresses — 배송지

### 8.1 목록

```
GET /addresses
```

**Auth required**

**Response 200**: `Address[]` (default가 첫 번째)

### 8.2 추가

```
POST /addresses
```

**Auth required**

**Body**
```json
{
  "label": "집",
  "recipient": "박은영",
  "phone": "010-1234-5678",
  "zipcode": "04101",
  "address": "서울특별시 마포구 양화로 45",
  "addressDetail": "메세나폴리스 1503호",
  "memo": "부재 시 경비실",
  "isDefault": true
}
```

`isDefault: true`면 다른 주소들의 default 자동 해제.

**Response 201**: 생성된 address

### 8.3 수정

```
PATCH /addresses/{id}
```

**Auth required** · 본인 주소만 가능

**Body**: 변경할 필드만

**Response 200**

### 8.4 삭제

```
DELETE /addresses/{id}
```

**Auth required** · **204**

기본 배송지를 삭제하면 첫 번째 남은 주소를 기본으로 자동 승격.

### 8.5 기본 설정

```
POST /addresses/{id}/default
```

**Auth required** · **204**

---

## 9. Orders — 주문

### 9.1 주문 생성

```
POST /orders
```

**Auth required** · 본인인증 필수 (없으면 `IDENTITY_REQUIRED`)

**Body**
```json
{
  "items": [
    { "productId": "p1", "qty": 1 }
  ],
  "addressId": "addr_xyz",        // 또는 inline address 객체
  "deliveryMethod": "direct",      // direct | cargo
  "paymentMethod": "card",          // card | bank | easy
  "memo": "부재 시 경비실"
}
```

서버 처리:
1. 본인인증 확인
2. 재고 확인 (실패 → `OUT_OF_STOCK`)
3. 가격 재검증 (변동 시 → `PRICE_CHANGED`, 신규 가격 응답)
4. 주문 생성 (status: `PENDING_PAYMENT`)
5. 주문 ID 응답 → 클라이언트가 `/payments/init` 호출

**Response 201**
```json
{
  "data": {
    "order": { ...Order, "status": "PENDING_PAYMENT" },
    "payment": {
      "paymentId": "pay_abc",
      "pgInitData": { ... }            // PG SDK 초기화에 필요한 데이터
    }
  }
}
```

### 9.2 내 주문 목록

```
GET /orders
```

**Auth required**

**Query**
| 파라미터 | 설명 |
|---|---|
| `status` | `결제완료`, `준비중`, `배송중`, `배송완료`, `취소` 또는 `all` |
| `from`, `to` | YYYY-MM-DD 범위 |
| `page`, `size` | 페이지네이션 |

**Response 200**: `Order[]` (최신순)

### 9.3 주문 상세

```
GET /orders/{id}
```

**Auth required** · 본인 주문만

**Response 200**
```json
{
  "data": {
    "id": "RK-26050001",
    "status": "배송중",
    "createdAt": "...",
    "items": [ ...OrderLineItem[] ],
    "itemsTotal": 708000,
    "shippingFee": 40000,
    "total": 748000,
    "deliveryMethod": "direct",
    "paymentMethod": "card",
    "paymentMethodLabel": "신한카드 1234",
    "address": { ...OrderAddress },
    "estimatedDelivery": "5월 3일(토) ~ 5월 4일(일)",
    "tracking": { "carrier": "내부직송", "number": null },
    "timeline": [
      { "status": "결제완료", "at": "2026-05-01T09:24:00Z" },
      { "status": "준비중", "at": "2026-05-01T15:00:00Z" }
    ]
  }
}
```

### 9.4 주문 취소

```
POST /orders/{id}/cancel
```

**Auth required** · 본인 주문, status가 `결제완료` or `준비중`일 때만

**Body**
```json
{ "reason": "단순 변심" }
```

`배송중` 이후는 환불 절차 (9.5)로.

PG에 결제 취소 요청 (Payment 7.4 호출).

**Response 200**: 갱신된 order

### 9.5 환불 신청

```
POST /orders/{id}/refund
```

**Auth required**

**Body**
```json
{
  "reason": "동작 불량",
  "items": [ { "productId": "p1", "qty": 1 } ],   // 부분 환불 시
  "imageIds": ["img_xxx"]                           // 첨부 이미지 (별도 업로드)
}
```

상태 → `환불요청` → 운영자 승인 후 `환불완료`.

**Response 201**: 생성된 refund 요청

### 9.6 배송 조회

```
GET /orders/{id}/tracking
```

**Auth required**

**Response 200**
```json
{
  "data": {
    "carrier": "한진택배",
    "trackingNumber": "5821-0091-2345",
    "events": [
      { "at": "...", "location": "서울 마포", "status": "배송 출발" },
      ...
    ]
  }
}
```

직접배송의 경우 `carrier: "내부직송"`, 기사 연락처와 ETA만 응답.

---

## 10. Payments — 결제 (PG 연동)

> **중요**: 카드번호·CVC·OTP 등 결제 비밀 정보는 절대 rekit 서버를 거치지 않습니다.
> PG (토스페이먼츠 / 포트원 / KG이니시스 등)의 결제 위젯이 클라이언트 ↔ PG 간 직접 통신.
> rekit 서버는 거래 ID와 검증 결과만 보관.

### 10.1 결제 초기화

```
POST /payments/init
```

**Auth required**

**Body**
```json
{ "orderId": "RK-26050001", "method": "card" }
```

서버 처리:
- order 검증 (소유자, status가 `PENDING_PAYMENT`)
- PG에 결제 요청 생성 → `paymentKey` 발급
- 클라이언트가 위젯 띄울 때 사용할 데이터 응답

**Response 200**
```json
{
  "data": {
    "paymentKey": "pay_xyz",
    "amount": 748000,
    "orderId": "RK-26050001",
    "successUrl": "https://rekit.kr/payments/success",
    "failUrl": "https://rekit.kr/payments/fail",
    "pgProvider": "tosspayments"
  }
}
```

### 10.2 결제 검증

```
POST /payments/verify
```

**Auth required** · PG 위젯이 success로 redirect한 후 클라이언트가 호출

**Body**
```json
{
  "paymentKey": "pay_xyz",
  "orderId": "RK-26050001",
  "amount": 748000
}
```

서버 처리:
- PG 검증 API 호출 (서버↔PG)
- 금액·orderId 일치 확인
- order status → `결제완료`, payment record 생성
- 카트에서 결제된 라인 제거 (옵션)
- `Order` 응답

**Response 200**
```json
{
  "data": {
    "order": { ...Order, "status": "결제완료" },
    "payment": { ...Payment }
  }
}
```

**Errors**: `PAYMENT_FAILED` (422)

### 10.3 PG 웹훅

```
POST /payments/webhook/{provider}
```

**Public** (단, signature 검증 필수)

PG가 비동기로 보내는 결과 알림 (재시도 안전 — 멱등 처리 필수).

Header `X-PG-Signature`로 위변조 확인.

**Response 200** (어떤 메시지든 200으로 ack — PG가 재시도하지 않도록)

### 10.4 결제 취소

```
POST /payments/{id}/cancel
```

**Auth required** · 운영자 또는 사용자 본인

**Body**
```json
{ "reason": "주문 취소", "amount": null }   // null이면 전액
```

서버 → PG 취소 API → 응답.

**Response 200**

### 10.5 부분/전체 환불

```
POST /payments/{id}/refund
```

**Auth required** · 보통 운영자가 호출 (사용자는 9.5 환불 신청)

**Body**
```json
{ "amount": 180000, "reason": "동작 불량 환불" }
```

**Response 200**

---

## 11. Help — 공지·FAQ·문의

### 11.1 공지사항 목록

```
GET /notices
```

**Public**

**Query**: `tag`, `page`, `size`

**Response 200**
```json
{
  "data": [
    {
      "id": "n_001",
      "title": "5월 한정, 직배송비 50% 할인",
      "tag": "이벤트",
      "publishedAt": "2026-04-30T00:00:00Z",
      "summary": "..."
    }
  ]
}
```

### 11.2 공지 상세

```
GET /notices/{id}
```

**Public**

**Response 200**: `Notice` (body 포함, Markdown 또는 sanitized HTML)

### 11.3 FAQ 목록

```
GET /faqs
```

**Public**

**Query**: `category` (선택)

**Response 200**
```json
{
  "data": [
    { "id": "f_001", "category": "주문/배송", "question": "...", "answer": "..." }
  ]
}
```

### 11.4 문의 제출

```
POST /help/contact
```

**Public** (비로그인도 OK)

**Body**
```json
{
  "topic": "주문/배송",
  "email": "you@example.com",
  "message": "...",
  "orderId": null,           // 선택
  "userId": null              // 로그인 시 자동 채움 (서버가 token에서 추출)
}
```

처리: 운영팀 알림 (이메일/슬랙) + DB 저장 + 사용자에게 접수 확인 메일.

**Response 201**
```json
{ "data": { "inquiryId": "inq_xxx", "estimatedReplyDays": 2 } }
```

---

## 12. Misc

### 12.1 우편번호 검색

```
GET /addresses/lookup?q=양화로
```

**Public**

**Response 200**
```json
{
  "data": [
    { "zipcode": "04101", "address": "서울특별시 마포구 양화로 45" }
  ]
}
```

> 또는 클라이언트에서 카카오 우편번호 SDK (postcode.map.daum.net) 직접 사용 권장 — 백엔드 API 불필요.

---

## 13. 데이터 모델 (요약)

### User
| 필드 | 타입 | 비고 |
|---|---|---|
| id | string | `u_` + ULID |
| username | string | unique, `[a-zA-Z0-9_]{4,20}` |
| name | string | |
| email | string | unique |
| phone | string? | 본인인증 시 채워짐 |
| verified | boolean | 본인인증 여부 |
| ecoKg | int | 누적 재사용량 (kg) |
| createdAt | datetime | |
| marketingOptIn | boolean | |

### Product
| 필드 | 타입 | 비고 |
|---|---|---|
| id | string | `p_` + ULID |
| title | string | |
| brand | string | |
| model | string | |
| year | string | "2021년식" 표시용 |
| kind | enum | fridge/washer/tv/aircon/microwave/vacuum |
| category | string | "냉장고", "세탁기" 등 |
| tone | enum | UI 색상 (생략 가능, 기본 mint) |
| grade | enum | A / B / C |
| price | int | 원 |
| originalPrice | int | 원가 |
| warranty | boolean | 동작보증 |
| stock | int | |
| tag | string? | "동작보증", "신규입고" 등 |
| images | Image[] | |
| specs | object | 자유 key-value |
| createdAt | datetime | |

### Address
| 필드 | 타입 |
|---|---|
| id | string |
| userId | string |
| label | string? |
| recipient | string |
| phone | string |
| zipcode | string |
| address | string |
| addressDetail | string |
| memo | string? |
| isDefault | boolean |

### CartItem
| 필드 | 타입 |
|---|---|
| productId | string |
| qty | int |
| selected | boolean |

### Order
| 필드 | 타입 |
|---|---|
| id | string | `RK-` + YYMMDD + seq |
| userId | string |
| status | enum | PENDING_PAYMENT / 결제완료 / 준비중 / 배송중 / 배송완료 / 취소 / 환불요청 / 환불완료 |
| items | OrderLineItem[] |
| itemsTotal | int |
| shippingFee | int |
| total | int |
| deliveryMethod | enum | direct / cargo |
| paymentMethod | enum | card / bank / easy |
| paymentId | string |
| address | OrderAddress (snapshot) |
| estimatedDelivery | string |
| createdAt | datetime |
| timeline | TimelineEvent[] |

### OrderLineItem
productId, qty, **price** (구매 시점 스냅샷), title, brand

### Payment
| 필드 | 타입 |
|---|---|
| id | string |
| orderId | string |
| pgProvider | string |
| pgPaymentKey | string |
| pgTransactionId | string |
| amount | int |
| method | enum |
| methodLabel | string |
| status | enum | INITIATED / SUCCESS / FAILED / CANCELLED / REFUNDED |
| createdAt | datetime |

### WishlistItem
userId, productId, addedAt

### Notice
id, title, body (markdown), tag, publishedAt, updatedAt

### Faq
id, category, question, answer, order

### ContactInquiry
id, userId?, topic, email, message, orderId?, status (NEW/IN_PROGRESS/RESOLVED), createdAt, repliedAt?

---

## 14. 향후 추가 (admin / 미구현 화면)

다음 도메인은 클라이언트 미구현 상태이므로 우선순위 낮음:

- **Admin**: `/admin/*` — 대시보드 통계, 상품 등록/수정, 주문 처리, 회원 관리, 매출 정산. 권한 체계 (RBAC) 필요.
- **Seller**: `/sell` 판매자 등록 — 협력 철거업체 입점 신청 폼.
- **Notifications**: 푸시·SMS·이메일 알림 발송 시스템.
- **Reviews**: 상품 후기 (디자인 미완)
- **Coupons / Points**: 할인쿠폰·적립금 (디자인 미완)

---

## 15. 비기능 요구사항

| 항목 | 목표 |
|---|---|
| P95 응답 시간 | 일반 read 200ms, write 500ms |
| 가용성 | 99.9% (월 43분 다운) |
| 백업 | DB 일 1회 + WAL 5분 단위 |
| 로그 | 모든 mutation 감사 로그 1년 보관 |
| 모니터링 | Sentry (에러), Datadog 또는 Grafana (메트릭) |
| 개인정보 암호화 | 휴대폰·이메일 양방향, 비밀번호 단방향 (argon2id) |
| 백엔드 언어 추천 | Spring Boot (Kotlin) / NestJS / Django REST — 팀 역량 따라 |

---

## 16. 변경 이력

| 일자 | 버전 | 내용 |
|---|---|---|
| 2026-05-01 | v1.0 | 초안 — 50개 엔드포인트, 9개 도메인 |
