# Rekle SLO (서비스 수준 목표)

> todo O6-1. 알림 규칙은 `infra/monitoring/prometheus/rules/rekle-alerts.yml`, SLI 기록 규칙은
> `infra/monitoring/prometheus/rules/rekle-slo.yml`, 운영 방법은 `docs/monitoring.md`.

## 1. 원칙

- **측정 창**: 최근 **30일 이동 창(rolling)**. 월 단위 리뷰 때 그 시점의 30일 값을 기록한다.
- **측정 지점**: 앱 서버 측 메트릭(`rekle_*`, 미들웨어가 기록). 엣지 nginx·네트워크·브라우저 구간은 포함되지 않는다
  → 사용자 체감은 이보다 조금 나쁘다. 앱이 통째로 죽은 시간은 요청 자체가 안 들어와 아래 비율 SLI 에 안 잡히므로
  **가동률 SLI(§2.5) 와 외부 업타임 모니터(todo O4-3)** 로 보완한다.
- **좋은 이벤트 / 전체 이벤트 비율**로 정의한다. 지연 SLO 도 "p95 < X" 를 "X 안에 끝난 요청 비율 ≥ 95%" 로 바꿔 잰다
  — 30일치 히스토그램으로 p95 를 계산하는 것보다 싸고, 버킷 경계(0.3s·1.0s)와 목표값이 같아 오차가 없다.
- **오류 예산** = 1 − 목표. 예산을 다 쓰면 기능 배포보다 안정화 작업을 우선한다.

## 2. SLI / SLO

| # | SLI | 목표 (30일) | 오류 예산 |
|---|---|---|---|
| 1 | 가용성 — 5xx 가 아닌 응답 비율 | **≥ 99.5%** (5xx < 0.5%) | 요청 10만 건당 500건 |
| 2 | 조회 API 지연 — GET `/api/v1/*`(관리자 제외) 중 300ms 안에 끝난 비율 | **≥ 95%** (= p95 < 300ms) | 5% |
| 3 | 결제 승인 지연 — POST `/api/v1/payments/confirm` 중 1초 안에 끝난 비율 | **≥ 95%** (= p95 < 1s) | 5% |
| 4 | 결제 성공률 — PG 승인 호출 중 성공 비율 (토스 명시적 거절 제외) | **≥ 99%** | 1% |
| 5 | 가동률 — Prometheus 가 앱 `/metrics` 수집에 성공한 시간 비율 | **≥ 99.5%** | 30일 중 약 3시간 36분 |

### 2.1 가용성 (5xx 비율)

```promql
# 30일 (기록 규칙 사용 — 가볍다)
sum_over_time(rekle:sli_availability_good:rate5m[30d])
/
sum_over_time(rekle:sli_availability_total:rate5m[30d])

# 기록 규칙 없이 직접 (기록 규칙 도입 전 구간 포함 시)
1 - (
  sum(increase(rekle_http_requests_total{path!="<unmatched>",status=~"5.."}[30d]))
  /
  sum(increase(rekle_http_requests_total{path!="<unmatched>"}[30d]))
)
```

- 503 `SERVICE_BUSY`(DB 풀 타임아웃) 도 5xx 이므로 **포함**한다 — 사용자 입장에선 실패다.
- 4xx 는 실패가 아니다 (입력 오류·인증 필요·재고 없음 등 정상 거절).

### 2.2 조회 API 지연

```promql
sum_over_time(rekle:sli_read_latency_good:rate5m[30d])
/
sum_over_time(rekle:sli_read_latency_total:rate5m[30d])

# 직접
sum(increase(rekle_http_request_duration_seconds_bucket{method="GET",path=~"/api/v1/.+",path!~"/api/v1/admin/.*",le=~"0\\.3"}[30d]))
/
sum(increase(rekle_http_request_duration_seconds_count{method="GET",path=~"/api/v1/.+",path!~"/api/v1/admin/.*"}[30d]))
```

- 대시보드용 순간값(p95): `histogram_quantile(0.95, sum by (le) (rate(rekle_http_request_duration_seconds_bucket{method="GET",path=~"/api/v1/.+",path!~"/api/v1/admin/.*"}[5m])))`
- `le` 를 정규식으로 쓰는 이유: `prometheus_client` 는 `"0.3"`·`"1.0"` 으로 내보내는데 Prometheus 3 은 수집 시
  `"1"` 처럼 정규화할 수 있다. 두 표기 모두 매칭.

### 2.3 결제 승인 지연

```promql
sum_over_time(rekle:sli_confirm_latency_good:rate5m[30d])
/
sum_over_time(rekle:sli_confirm_latency_total:rate5m[30d])

# 직접
sum(increase(rekle_http_request_duration_seconds_bucket{method="POST",path="/api/v1/payments/confirm",le=~"1|1\\.0"}[30d]))
/
sum(increase(rekle_http_request_duration_seconds_count{method="POST",path="/api/v1/payments/confirm"}[30d]))
```

- 토스 API 호출 시간을 **포함**한 엔드투엔드 서버 시간이다. 원인 분리는 `rekle_pg_request_duration_seconds{operation="confirm"}`.

### 2.4 결제 성공률

```promql
sum_over_time(rekle:sli_payment_good:rate5m[30d])
/
sum_over_time(rekle:sli_payment_total:rate5m[30d])

# 직접
sum(increase(rekle_payment_confirm_total{result="success"}[30d]))
/
sum(increase(rekle_payment_confirm_total{result=~"success|unknown"}[30d]))
```

- **분모에서 제외: `result="failed"`** — 토스가 명시적으로 거절한 건(카드 한도 초과·잔액 부족·사용자 인증 실패 등)은
  우리 시스템 품질이 아니다. `unknown`(타임아웃·통신 실패 — 결과를 모름)은 우리/연동 품질 문제로 보고 **실패로 센다**.
- **애초에 집계 안 됨**: PG 호출 전 사전 거절(금액 불일치·주문 상태 불일치·결제 건 없음). 멱등 재요청(이미 PAID) 도 PG 를 안 불러 미집계.
- 주의: 우리 설정 오류(시크릿 키 오류 등)로 토스가 4xx 를 주면 `failed` 로 분류돼 이 SLI 에서 빠진다
  → `failed` 비율이 평소보다 급증하면 별도로 확인 (서비스 대시보드 "결제 승인 결과" 패널).
- 결제 건수가 적은 MVP 단계에서는 1건이 수 % 를 움직인다 — 30일 결제 수가 100건 미만이면 "참고값" 으로만 본다.

### 2.5 가동률

```promql
avg_over_time(up{job="rekle-app"}[30d])
```

- 배포 중 재기동(수십 초)도 깎인다. 정확한 외부 관점 가동률은 업타임 모니터(`/health/ready`, 1분 주기) 값을 우선한다.
- Prometheus 자체가 죽은 구간은 데이터가 없어 계산에서 빠진다 (과대평가 방향).

## 3. 공통 제외 대상

| 제외 | 이유 / 방법 |
|---|---|
| `/health`, `/health/ready`, `/metrics` | 앱 미들웨어가 애초에 메트릭에서 제외 |
| `path="<unmatched>"` | 라우트 미매칭(스캐너·CORS preflight) — 우리 기능이 아님 |
| 관리자 API (`/api/v1/admin/*`) | 지연 SLI 에서만 제외 (내부 사용자, 무거운 집계). 가용성에는 포함 |
| 계획된 점검 시간 | 사전 공지한 점검 구간은 월 리뷰 때 해당 구간을 빼고 다시 계산하고 기록에 남긴다 |
| 부하테스트 트래픽 | 운영에서 부하테스트 금지(todo O7) — 스테이징 Prometheus 는 별도라 섞이지 않음 |
| 토스 명시적 거절 | 결제 성공률 SLI 의 분모에서만 제외 (§2.4) |

## 4. 알림과의 관계

SLO 는 30일 목표이고, 알림은 "지금 예산을 빠르게 태우는 중" 을 잡는다 (`rekle-alerts.yml`).

| SLO | 연결된 알림 |
|---|---|
| 가용성 | `RekleHigh5xxRatio` (5분 5xx > 2%, 5분 지속 — 예산 0.5% 를 4배 속도로 소진), `RekleDbPoolTimeouts` |
| 결제 성공률 | `ReklePaymentUnknown` (1건이라도 즉시 — 돈 정합성 문제), `RekleTossLatencyHigh` |
| 가동률 | `RekleAppDown`, `ReklePostgresDown`, `RekleRedisDown` |
| 지연 | 직접 알림 없음 — 대시보드·월 리뷰. `RekleEventLoopLagHigh` 가 대표적 원인(블로킹)을 잡는다 |

향후 트래픽이 충분해지면 다중 창 소진율(burn rate) 알림(예: 1h·5m 창 모두 소진율 14.4 초과)으로 교체를 검토한다.

## 5. 리뷰

- 매월 1회: §2 의 30일 값을 `docs/perf/` 또는 운영 노트에 기록. 예산 초과 SLO 는 원인과 조치 기록.
- 목표값은 첫 3개월 실측 후 재조정 (지금 값은 추정치).
