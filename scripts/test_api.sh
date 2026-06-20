#!/usr/bin/env bash
# API 엔드투엔드 스모크 테스트
# 실행: bash scripts/test_api.sh
# 의존: curl, jq

set -eo pipefail

BASE="http://localhost:8000/api/v1"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[PASS]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }
step() { echo -e "\n${YELLOW}── $1 ──${NC}"; }

assert_status() {
  local label="$1" expected="$2" actual="$3" body="${4:-}"
  if [ "$actual" -eq "$expected" ]; then
    ok "$label (HTTP $actual)"
  else
    fail "$label — expected $expected, got $actual"
    [ -n "$body" ] && echo "      body: $body" || true
  fi
}

# ── 1. 인증 ──────────────────────────────────────────────────────
step "인증"

# 유저 로그인
RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/auth/sign-in" \
  -H "Content-Type: application/json" \
  -d '{"loginId":"hong001","password":"User1234!"}')
HTTP_CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "유저 로그인 (POST /auth/sign-in)" 200 "$HTTP_CODE" "$BODY"
USER_TOKEN=$(echo "$BODY" | jq -r '.accessToken')

# 어드민 로그인
RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/auth/sign-in" \
  -H "Content-Type: application/json" \
  -d '{"loginId":"admin01","password":"Admin1234!"}')
HTTP_CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "어드민 로그인 (POST /auth/sign-in)" 200 "$HTTP_CODE" "$BODY"
ADMIN_TOKEN=$(echo "$BODY" | jq -r '.accessToken')

# GET /users/me
RESP=$(curl -s -w "\n%{http_code}" "$BASE/users/me" \
  -H "Authorization: Bearer $USER_TOKEN")
HTTP_CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "GET /users/me" 200 "$HTTP_CODE"
echo "    유저: $(echo "$BODY" | jq -r '.username // .login_id')"

# ── 2. 배송지 조회 (order/payment 에서 사용) ──────────────────────
step "배송지"

RESP=$(curl -s -w "\n%{http_code}" "$BASE/addresses" \
  -H "Authorization: Bearer $USER_TOKEN")
HTTP_CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "GET /addresses" 200 "$HTTP_CODE"
ADDRESS_ID=$(echo "$BODY" | jq '.[0].id')
echo "    기본 배송지 ID: $ADDRESS_ID"

# ── 사전 재고 리셋 (재실행 안전) ─────────────────────────────────
step "사전 준비 (재고 리셋)"

# 테스트에 사용할 product 5 (냉장고) 와 product 6 (청소기) 재고 복구
for PID_STOCK in "5:1" "6:2"; do
  PID="${PID_STOCK%%:*}"; STOCK="${PID_STOCK##*:}"
  curl -s -X PATCH "$BASE/admin/products/$PID" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"stock\":$STOCK,\"status\":\"ACTIVE\"}" > /dev/null
  ok "상품 $PID 재고 → $STOCK 복구"
done

# ── 3. 상품 카탈로그 ──────────────────────────────────────────────
step "상품 카탈로그"

RESP=$(curl -s -w "\n%{http_code}" "$BASE/products")
HTTP_CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "GET /products" 200 "$HTTP_CODE"
PRODUCT_COUNT=$(echo "$BODY" | jq '.meta.total')
echo "    상품 수: $PRODUCT_COUNT"

PRODUCT_ID=$(echo "$BODY" | jq '.items[0].id')
echo "    첫 상품 ID: $PRODUCT_ID"

RESP=$(curl -s -w "\n%{http_code}" "$BASE/products/$PRODUCT_ID")
HTTP_CODE=$(echo "$RESP" | tail -1)
assert_status "GET /products/$PRODUCT_ID" 200 "$HTTP_CODE"

RESP=$(curl -s -w "\n%{http_code}" "$BASE/products?q=LG")
HTTP_CODE=$(echo "$RESP" | tail -1)
assert_status "GET /products?q=LG" 200 "$HTTP_CODE"

RESP=$(curl -s -w "\n%{http_code}" "$BASE/products?category=REFRIGERATOR")
HTTP_CODE=$(echo "$RESP" | tail -1)
assert_status "GET /products?category=REFRIGERATOR" 200 "$HTTP_CODE"

# ── 4. 관심상품 ──────────────────────────────────────────────────
step "관심상품 (Favorites)"

RESP=$(curl -s -w "\n%{http_code}" "$BASE/favorites" \
  -H "Authorization: Bearer $USER_TOKEN")
HTTP_CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "GET /favorites" 200 "$HTTP_CODE"
echo "    관심상품 수: $(echo "$BODY" | jq 'length')"

RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/favorites/$PRODUCT_ID" \
  -H "Authorization: Bearer $USER_TOKEN")
HTTP_CODE=$(echo "$RESP" | tail -1)
assert_status "POST /favorites/$PRODUCT_ID (추가)" 200 "$HTTP_CODE"

RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/favorites/$PRODUCT_ID" \
  -H "Authorization: Bearer $USER_TOKEN")
HTTP_CODE=$(echo "$RESP" | tail -1)
assert_status "POST /favorites/$PRODUCT_ID (재추가 idempotent)" 200 "$HTTP_CODE"

RESP=$(curl -s -w "\n%{http_code}" -X DELETE "$BASE/favorites/$PRODUCT_ID" \
  -H "Authorization: Bearer $USER_TOKEN")
HTTP_CODE=$(echo "$RESP" | tail -1)
assert_status "DELETE /favorites/$PRODUCT_ID" 200 "$HTTP_CODE"

# ── 5. 장바구니 ──────────────────────────────────────────────────
step "장바구니 (Cart)"

# 테스트 전 장바구니 초기화 (재실행 안전)
CART_RESP=$(curl -s "$BASE/cart" -H "Authorization: Bearer $USER_TOKEN")
EXISTING_IDS=$(echo "$CART_RESP" | jq '[.items[].id]')
if [ "$EXISTING_IDS" != "[]" ] && [ "$EXISTING_IDS" != "null" ]; then
  curl -s -X POST "$BASE/cart/items/bulk-delete" \
    -H "Authorization: Bearer $USER_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"item_ids\":$EXISTING_IDS}" > /dev/null
  echo "    기존 장바구니 비움: $EXISTING_IDS"
fi

# GET /cart (prefix 는 /cart, 목록은 빈 path)
RESP=$(curl -s -w "\n%{http_code}" "$BASE/cart" \
  -H "Authorization: Bearer $USER_TOKEN")
HTTP_CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "GET /cart" 200 "$HTTP_CODE"
echo "    장바구니 항목 수: $(echo "$BODY" | jq '.items | length')"

RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/cart/items" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"product_id\":$PRODUCT_ID,\"quantity\":1}")
HTTP_CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "POST /cart/items" 201 "$HTTP_CODE"
# 방금 추가한 item의 id
CART_ITEM_ID=$(echo "$BODY" | jq --argjson pid "$PRODUCT_ID" '[.items[] | select(.product.id==$pid)] | .[0].id')
echo "    추가된 cart_item id: $CART_ITEM_ID"

RESP=$(curl -s -w "\n%{http_code}" -X PATCH "$BASE/cart/items/$CART_ITEM_ID" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"quantity":1}')
HTTP_CODE=$(echo "$RESP" | tail -1)
assert_status "PATCH /cart/items/$CART_ITEM_ID (수량 변경)" 200 "$HTTP_CODE"

RESP=$(curl -s -w "\n%{http_code}" -X DELETE "$BASE/cart/items/$CART_ITEM_ID" \
  -H "Authorization: Bearer $USER_TOKEN")
HTTP_CODE=$(echo "$RESP" | tail -1)
assert_status "DELETE /cart/items/$CART_ITEM_ID" 204 "$HTTP_CODE"

# ── 6. 주문 ──────────────────────────────────────────────────────
step "주문 (Order)"

# 견적 (items 배열 + address_id 필요)
RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/orders/quote" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"items\": [{\"product_id\":$PRODUCT_ID,\"quantity\":1}],
    \"address_id\": $ADDRESS_ID,
    \"shipping_method\": \"FREIGHT\"
  }")
HTTP_CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "POST /orders/quote" 200 "$HTTP_CODE" "$BODY"
echo "    배송비: $(echo "$BODY" | jq '.shipping_fee')"

# 주문 생성
RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/orders" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"items\": [{\"product_id\":$PRODUCT_ID,\"quantity\":1}],
    \"address_id\": $ADDRESS_ID,
    \"shipping_method\": \"FREIGHT\"
  }")
HTTP_CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "POST /orders" 201 "$HTTP_CODE" "$BODY"
ORDER_NUMBER=$(echo "$BODY" | jq -r '.order_number')
echo "    주문번호: $ORDER_NUMBER"

RESP=$(curl -s -w "\n%{http_code}" "$BASE/orders" \
  -H "Authorization: Bearer $USER_TOKEN")
HTTP_CODE=$(echo "$RESP" | tail -1)
assert_status "GET /orders" 200 "$HTTP_CODE"

RESP=$(curl -s -w "\n%{http_code}" "$BASE/orders/$ORDER_NUMBER" \
  -H "Authorization: Bearer $USER_TOKEN")
HTTP_CODE=$(echo "$RESP" | tail -1)
assert_status "GET /orders/$ORDER_NUMBER" 200 "$HTTP_CODE"

# ── 7. 결제 초기화 ────────────────────────────────────────────────
step "결제 (Payment)"

RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/payments/init" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"order_number\":\"$ORDER_NUMBER\",\"method\":\"CARD\"}")
HTTP_CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "POST /payments/init" 201 "$HTTP_CODE" "$BODY"
echo "    payment_id: $(echo "$BODY" | jq '.payment_id')"
echo "    amount: $(echo "$BODY" | jq '.amount')"

# 주문 취소 (결제 전 PENDING 상태에서 가능)
RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/orders/$ORDER_NUMBER/cancel" \
  -H "Authorization: Bearer $USER_TOKEN")
HTTP_CODE=$(echo "$RESP" | tail -1)
assert_status "POST /orders/$ORDER_NUMBER/cancel" 200 "$HTTP_CODE"

# ── 8. 관리자 상품 CRUD ──────────────────────────────────────────
step "관리자 상품 CRUD"

RESP=$(curl -s -w "\n%{http_code}" "$BASE/admin/products" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
HTTP_CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "GET /admin/products" 200 "$HTTP_CODE"
echo "    전체 상품 수: $(echo "$BODY" | jq '.meta.total')"

RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/admin/products" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "테스트 전자레인지",
    "description": "테스트용 상품입니다.",
    "category": "KITCHEN",
    "condition_grade": "B",
    "warranty_works": true,
    "price": 50000,
    "stock": 3,
    "image_urls": []
  }')
HTTP_CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "POST /admin/products" 201 "$HTTP_CODE" "$BODY"
NEW_PRODUCT_ID=$(echo "$BODY" | jq '.id')
echo "    생성된 상품 ID: $NEW_PRODUCT_ID"

RESP=$(curl -s -w "\n%{http_code}" -X PATCH "$BASE/admin/products/$NEW_PRODUCT_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"price": 45000, "description": "가격 인하"}')
HTTP_CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "PATCH /admin/products/$NEW_PRODUCT_ID" 200 "$HTTP_CODE"
echo "    수정 후 가격: $(echo "$BODY" | jq '.price')"

RESP=$(curl -s -w "\n%{http_code}" -X DELETE "$BASE/admin/products/$NEW_PRODUCT_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
HTTP_CODE=$(echo "$RESP" | tail -1)
assert_status "DELETE /admin/products/$NEW_PRODUCT_ID (soft)" 204 "$HTTP_CODE"

# 일반유저 → 403
RESP=$(curl -s -w "\n%{http_code}" "$BASE/admin/products" \
  -H "Authorization: Bearer $USER_TOKEN")
HTTP_CODE=$(echo "$RESP" | tail -1)
assert_status "GET /admin/products (일반유저 → 403)" 403 "$HTTP_CODE"

echo -e "\n${GREEN}=== 테스트 완료 ===${NC}"
