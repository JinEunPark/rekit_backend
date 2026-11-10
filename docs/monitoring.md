# 모니터링 운영 가이드

> todo O5·O6·O7 관련. SLO 정의는 `docs/slo.md`. 파일 위치:
>
> | 경로 | 내용 |
> |---|---|
> | `infra/monitoring/docker-compose.yml` | **로컬** 스택 (Prometheus 9090 · Grafana 3000, 익명 로그인) |
> | `infra/monitoring/prod/` | **운영** 스택 (compose · prometheus.yml · alertmanager · `.env.example`) |
> | `infra/monitoring/prometheus/rules/` | 알림(`rekle-alerts.yml`)·SLI 기록(`rekle-slo.yml`) 규칙 — 로컬·운영 공용 |
> | `infra/monitoring/prometheus/tests/` | 알림 규칙 단위 테스트 (`promtool test rules`) |
> | `infra/monitoring/grafana/` | provisioning + 대시보드 3종 (서비스 · 부하테스트 · 인프라) — 로컬·운영 공용 |

## 1. 구성

운영 서버에 앱과 **별도 compose 프로젝트(`rekle-monitoring`)** 로 띄운다 (O5-1 기본안). 포트는 전부 127.0.0.1.

| 컨테이너 | 역할 | 호스트 포트 |
|---|---|---|
| `rekle-mon-prometheus` | 수집·저장(30일/10GB)·규칙 평가, k6 remote write 수신 | 127.0.0.1:9091 |
| `rekle-mon-alertmanager` | 알림 묶기·슬랙 발송 | 127.0.0.1:9093 |
| `rekle-mon-grafana` | 대시보드 (익명 접근 없음) | 127.0.0.1:3300 (+ `rekit_edge` 네트워크) |
| `rekle-mon-node-exporter` | 서버 CPU·메모리·디스크 | 없음 (내부) |
| `rekle-mon-cadvisor` | 컨테이너별 CPU·메모리·재시작 | 없음 |
| `rekle-mon-postgres-exporter` | 커넥션·트랜잭션·데드락·락 | 없음 |
| `rekle-mon-redis-exporter` | 메모리·클라이언트·ops | 없음 |
| (레포 밖) `seaweedfs` | S3 요청·오류·지연·volume·디스크 — weed 내장 `/metrics` (§3b) | 없음 |

네트워크: Prometheus·exporter 는 앱 프로젝트의 기본 네트워크 `rekit-backend_default`(Jenkins 가 `-p rekit-backend`
로 띄우므로 이 이름)에 붙어 `rekle-app:8000`·`rekle-postgres:5432`·`rekle-redis:6379` 에 컨테이너명으로 접근한다.
이름이 다르면 `REKLE_APP_NETWORK` 로 바꾼다:

```bash
docker inspect rekle-postgres --format '{{json .NetworkSettings.Networks}}'   # 키 이름이 네트워크명
```

> 별도 모니터링 서버로 옮길 때: `prod/` 디렉터리를 통째로 옮기고 `prod/prometheus.yml` 의 target 을 앱 서버 주소로,
> node_exporter·cAdvisor·DB/Redis exporter 는 앱 서버에 남겨 그 포트만 모니터링 서버 IP 에 연다.

## 2. 최초 배포 (서버에서 직접)

```bash
ssh externalhost
# 1) 레포의 infra/monitoring 을 서버에 둔다 (prod/ 가 ../prometheus, ../grafana 를 상대경로로 참조 — 디렉터리 통째로)
#    로컬에서: rsync -a --exclude 'prod/.env' --exclude 'prod/secrets' infra/monitoring/ externalhost:~/rekit/monitoring/
cd ~/rekit/monitoring

# 2) 시크릿
cp prod/.env.example ~/rekit/secrets/rekle_monitoring.env && chmod 600 ~/rekit/secrets/rekle_monitoring.env
vi ~/rekit/secrets/rekle_monitoring.env          # GF_SECURITY_ADMIN_PASSWORD, PG_MONITOR_PASSWORD 채우기
mkdir -p ~/rekit/secrets/alertmanager && chmod 700 ~/rekit/secrets/alertmanager
#    env 파일에 ALERTMANAGER_SECRETS_DIR=/home/wlsdms/rekit/secrets/alertmanager

# 3) Postgres 모니터링 계정 (§3) → 4) 슬랙 웹훅 (§4)

# 5) 기동
docker compose -f prod/docker-compose.yml --env-file ~/rekit/secrets/rekle_monitoring.env up -d
docker compose -p rekle-monitoring ps
```

확인:

```bash
curl -s localhost:9091/api/v1/targets | grep -o '"health":"[a-z]*"' | sort | uniq -c   # 전부 up 이어야 함
docker logs rekle-mon-grafana 2>&1 | grep -i 'level=error'                            # provisioning 오류 없는지
```

설정·규칙만 바꿨을 땐 재기동 없이: `curl -X POST localhost:9091/-/reload` (Prometheus), `curl -X POST localhost:9093/-/reload` (Alertmanager).
Grafana 대시보드 JSON 은 30초 안에 자동 재로딩된다 (파일 provisioning — UI 에서 수정해도 저장 안 됨, JSON 을 고쳐서 반영).

**Grafana admin 비밀번호**: `GF_SECURITY_ADMIN_PASSWORD` 는 Grafana DB 가 처음 만들어질 때만 반영된다. 이후 변경:
`docker exec -it rekle-mon-grafana grafana cli admin reset-admin-password '<새 비밀번호>'`

## 3. Postgres 모니터링 계정 (`pg_monitor`)

앱 계정(`rekle`, 소유자)을 exporter 에 쓰지 않는다 — 읽기 전용 통계 롤만 가진 전용 계정:

```bash
docker exec -it rekle-postgres psql -U rekle -d rekle
```

```sql
CREATE ROLE rekle_monitor WITH LOGIN CONNECTION LIMIT 3;
\password rekle_monitor            -- 셸 history 에 비밀번호가 안 남게 프롬프트로 입력
GRANT pg_monitor TO rekle_monitor; -- pg_stat_*·pg_settings 읽기 (데이터 테이블 접근 권한 없음)
GRANT CONNECT ON DATABASE rekle TO rekle_monitor;
```

같은 비밀번호를 `PG_MONITOR_PASSWORD` 에. 공식 postgres 이미지의 `pg_hba.conf` 는 도커 네트워크 접속을 scram 으로 허용하므로 추가 설정 불필요.
`pg_stat_statements`(O5-4) 확장이 생성된 뒤엔 `prod/docker-compose.yml` postgres-exporter 에 `command: [--collector.stat_statements]`
를 추가하면 쿼리별 통계도 수집된다 (`pg_monitor` 롤로 읽을 수 있음).

## 3b. SeaweedFS 메트릭 (레포 밖 `~/rekit/seaweedfs`)

운영 SeaweedFS 는 컨테이너명 `seaweedfs`, 네트워크 `seaweedfs_default`, command `server -dir=/data -s3` (메트릭 포트 없음).
Prometheus 는 `seaweedfs_default` 에도 붙어 있고 job `seaweedfs` 로 `seaweedfs:9324` 를 긁는다 — **포트를 켜기 전엔 target 이 down**
으로 보이지만 알림은 울리지 않는다 (`SeaweedFSDown` 은 최근 7일 안에 메트릭을 한 번이라도 받은 뒤에만 활성).

1. `~/rekit/seaweedfs/docker-compose.yml` 의 command 에 `-metricsPort=9324` 추가:
   ```yaml
   command: server -dir=/data -s3 -metricsPort=9324
   ```
   9324 는 **publish 하지 않는다** (`ports:` 에 추가 X) — 같은 도커 네트워크의 Prometheus 만 접근
2. 컨테이너 재생성 필요 (command 변경): `cd ~/rekit/seaweedfs && docker compose up -d` — 수 초간 이미지 업로드·조회 불가 → 저트래픽 시간에
3. 확인:
   ```bash
   # weed 는 9324 를 컨테이너 IP 에만 바인딩한다 (localhost 아님)
   docker exec seaweedfs sh -c 'wget -qO- http://$(hostname -i):9324/metrics | grep -m3 ^SeaweedFS_'
   curl -s localhost:9091/api/v1/targets | grep -o '"job":"seaweedfs"[^}]*"health":"[a-z]*"'
   ```
4. "Rekle 인프라" 대시보드 SeaweedFS 행: 상태(volumes / max volumes), S3 요청·오류 코드·p95, 디스크, 앱 측 S3 호출 p95·오류

> ⚠️ 보안: 현재 SeaweedFS 의 9333·8080·8888·8333 이 `0.0.0.0` 으로 publish 돼 있다. 도커 publish 는 iptables 를 직접
> 건드려 **ufw 규칙을 우회**하므로 방화벽으로 막혀 있다고 가정하면 안 된다 → `127.0.0.1:8333:8333` 처럼 loopback 바인딩
> (엣지 nginx `/s3/` 는 도커 네트워크로 접근하므로 publish 자체가 불필요할 수도 있다). master(9333)·filer(8888) 는 인증 없이 전체 파일 조작 가능.

공식 대시보드(`seaweedfs/seaweedfs` 레포 `other/metrics/grafana_seaweedfs.json`)는 컴포넌트별 job(`seaweedfs-master` 등)과
`cluster` 라벨을 전제해 `weed server` 단일 프로세스 구성과 맞지 않아 넣지 않았다 — 필요하면 Import 후 변수 수정.

## 4. 알림 채널 (슬랙)

1. 슬랙 앱 → Incoming Webhooks → 알림 받을 채널 선택 → Webhook URL 복사
2. `echo 'https://hooks.slack.com/services/...' > ~/rekit/secrets/alertmanager/slack_webhook_url && chmod 600 $_`
3. `curl -X POST localhost:9093/-/reload` (파일은 발송 때마다 읽으므로 사실 reload 없이도 반영)
4. 테스트 발송:
   ```bash
   docker exec rekle-mon-alertmanager amtool alert add TestAlert severity=warning \
     --annotation='summary="테스트 알림"' --annotation='description="무시하세요"' \
     --alertmanager.url=http://localhost:9093
   ```

Alertmanager 는 설정 파일에 환경변수를 치환하지 않아서 시크릿을 **파일**(`api_url_file`)로 읽는다. 이메일로 바꾸려면
`prod/alertmanager/alertmanager.yml` 의 email 예시 주석(`auth_password_file`)을 쓴다. Sentry·업타임 모니터도 같은 채널로 모은다(O6-3).

### 알림 목록 (`rekle-alerts.yml`)

| 알림 | 조건 | 등급 |
|---|---|---|
| `RekleAppDown` | `up{job="rekle-app"}==0` 2분 | critical |
| `RekleHigh5xxRatio` | 5xx 비율 > 2% 5분 지속 (5분 20건 이상일 때만) | critical |
| `ReklePaymentUnknown` | 결제 승인 `unknown` 1건 이상 (앱 재기동 후 첫 건 포함) | critical |
| `ReklePostgresDown` / `RekleRedisDown` | `pg_up`/`redis_up` == 0 1분 (readiness 가 보는 의존성) | critical |
| `HostDiskUsageCritical` | 디스크 > 90% 5분 | critical |
| `RekleTossLatencyHigh` | 토스 API p95 > 3s 10분 | warning |
| `RekleDbPoolTimeouts` | 5분 내 풀 타임아웃 1건 이상 | warning |
| `RekleEventLoopLagHigh` | 루프 지연 p99 > 0.5s 5분 | warning |
| `ReklePostgresDeadlocks` | 10분 내 데드락 증가 | warning |
| `ReklePostgresConnectionsHigh` | 커넥션 > max_connections 80% 5분 | warning |
| `HostDiskUsageHigh` | 디스크 > 80% 10분 | warning |
| `ContainerRestarted` | 10분 내 컨테이너 재시작 (배포 재생성은 제외) | warning |
| `SeaweedFSDown` | `up{job="seaweedfs"}==0` 2분 (메트릭을 받은 적 있을 때만) | critical |
| `SeaweedFSS3ErrorsHigh` | SeaweedFS S3 5xx > 5% 10분 | warning |
| `MonitoringTargetDown` | exporter 수집 실패 5분 (seaweedfs 제외) | warning |

`RekleAppDown` 이 떠 있으면 `component=app` 알림(5xx·지연·풀)은 억제된다. CPU·메모리는 알림 없이 대시보드만.

규칙 수정 후 검증 (레포 루트에서):

```bash
M=infra/monitoring/prometheus
docker run --rm -v "$PWD/$M:/p" -w /p --entrypoint promtool prom/prometheus:v3.5.0 check rules rules/rekle-alerts.yml rules/rekle-slo.yml
docker run --rm -v "$PWD/$M:/p" -w /p/tests --entrypoint promtool prom/prometheus:v3.5.0 test rules rekle-alerts.test.yml
docker run --rm -v "$PWD/infra/monitoring/prod/alertmanager:/a" --entrypoint amtool prom/alertmanager:v0.28.1 check-config /a/alertmanager.yml
```

## 4b. 배포 시 주의 — 다음 앱 배포에서 Postgres 가 재생성된다

`docker-compose.prod.yml` 의 postgres 에 `command:`(`shared_preload_libraries=pg_stat_statements`, O5-4)가 추가됐다.
Jenkins deploy 잡은 `up -d postgres redis app` 이라 **설정이 바뀐 postgres 컨테이너를 재생성** → 수 초~수십 초 DB 다운타임
(데이터는 볼륨에 남는다).

1. 저트래픽 시간에 배포
2. 직전 백업: `docker exec rekle-postgres pg_dump -U rekle rekle > ~/backup_$(date +%F).sql`
3. 배포 후 확인:
   ```bash
   docker exec rekle-postgres psql -U rekle -d rekle -c 'SHOW shared_preload_libraries;'   # pg_stat_statements
   docker exec rekle-postgres psql -U rekle -d rekle -c '\dx'                               # 확장 생성(마이그레이션) 확인
   ```
4. 이후 postgres-exporter 에 `--collector.stat_statements` 를 켤 수 있다 (§3)
5. 모니터링 스택은 앱 네트워크(`rekit-backend_default`)에 외부 네트워크로 붙어 있어 앱 재배포에 영향 없음.
   단 앱 프로젝트를 `down` 하면 네트워크가 지워지려다 "network has active endpoints" 로 실패할 수 있다 →
   그땐 `docker compose -p rekle-monitoring stop` 후 진행

## 5. 접속

### SSH 터널 (기본)

```bash
ssh -N -L 3300:127.0.0.1:3300 -L 9091:127.0.0.1:9091 -L 9093:127.0.0.1:9093 externalhost
# Grafana http://localhost:3300 (admin / GF_SECURITY_ADMIN_PASSWORD)
#   서브경로 설정(GF_SERVER_SERVE_FROM_SUB_PATH=true)을 켰다면 http://localhost:3300/grafana/
# Prometheus http://localhost:9091 · Alertmanager http://localhost:9093
```

### 엣지 nginx `/grafana/` 서브경로 (선택)

> ⚠️ `rekit.co.kr/grafana` 는 쇼핑몰과 **같은 출처(origin)** 다. Grafana 에 XSS 취약점이 생기면 쇼핑몰 쿠키·API 를
> 같은 출처 권한으로 건드릴 수 있다 → 가능하면 `grafana.rekit.co.kr` 같은 **서브도메인이 더 안전**하다.
> 어느 쪽이든 앞단 접근 제한(IP 허용 목록 또는 basic auth)을 함께 건다.

1. env 파일에 `GF_SERVER_ROOT_URL=https://rekit.co.kr/grafana/`, `GF_SERVER_SERVE_FROM_SUB_PATH=true` → `up -d grafana`
   (Grafana 컨테이너는 이미 `rekit_edge` 네트워크에 붙어 있음)
2. `~/rekit/nginx` 설정 (레포 밖) — `http {}` 블록에 한 번:
   ```nginx
   map $http_upgrade $connection_upgrade { default upgrade; '' close; }
   ```
   server 블록(`rekit-locations.inc` 등):
   ```nginx
   location /grafana/ {
       # 접근 제한 — 둘 중 하나 이상
       allow 203.0.113.10;        # 사무실/집 고정 IP
       deny  all;
       # auth_basic "monitoring"; auth_basic_user_file /etc/nginx/htpasswd_grafana;

       # 변수 + resolver: Grafana 가 꺼져 있어도 nginx 가 기동 실패하지 않게 (도커 내장 DNS)
       resolver 127.0.0.11 valid=30s;
       set $grafana_upstream http://rekle-mon-grafana:3000;
       proxy_pass $grafana_upstream;   # URI 없이 → /grafana/... 그대로 전달 (serve_from_sub_path 와 짝)

       proxy_set_header Host              $host;
       proxy_set_header X-Real-IP         $remote_addr;
       proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
       # Grafana Live(웹소켓 /grafana/api/live/ws)
       proxy_http_version 1.1;
       proxy_set_header Upgrade           $http_upgrade;
       proxy_set_header Connection        $connection_upgrade;
   }
   ```
3. `docker exec nginx nginx -t && docker exec nginx nginx -s reload`
4. 확인: 허용 IP 에서 `https://rekit.co.kr/grafana/` 로그인 화면, 그 외 IP 는 403. 앱 `/metrics` 는 여전히 외부 비노출이어야 함 (O2-6)

### Jenkins `/jenkins` 서브경로 메모 (레포 밖 — 참고용)

- Jenkins 컨테이너에 `JENKINS_OPTS=--prefix=/jenkins` (env) → 재생성. 엣지 nginx 와 같은 `rekit_edge` 네트워크에 붙인다
- nginx:
  ```nginx
  location /jenkins/ {
      allow 203.0.113.10; deny all;          # 강력 권장 — Jenkins 는 곧 서버 셸 권한(빌드 스크립트·docker.sock)
      resolver 127.0.0.11 valid=30s;
      set $jenkins_upstream http://jenkins:8080;
      proxy_pass $jenkins_upstream;          # prefix 와 같은 경로를 그대로 전달
      proxy_set_header Host              $host;
      proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_set_header X-Forwarded-Port  443;
      proxy_http_version 1.1;               # 에이전트·로그 스트리밍
      proxy_request_buffering off;
  }
  ```
- Manage Jenkins → System → **Jenkins URL** = `https://rekit.co.kr/jenkins/` (틀리면 "reverse proxy setup is broken" 경고·CSRF crumb 오류)
- Security: **"Allow users to sign up" 끄기**, 권한 전략에서 **익명 읽기(Anonymous read) 비활성**, 관리자 계정 강한 비밀번호/2FA
- Jenkins 는 `docker.sock` 을 가진 사실상 root — IP 제한 없이 공개하지 말 것. 서브도메인 + IP 제한이 가장 안전

## 6. k6 → Prometheus remote write

Prometheus 는 `--web.enable-remote-write-receiver` 로 `/api/v1/write` 를 받는다 (로컬 9090, 운영형 9091).
**운영 서버에서 부하테스트 금지** — 스테이징 서버에 이 스택을 같이 띄우고 그 Prometheus 로 보낸다 (부하 생성기 → SSH 터널).

```bash
# (부하 생성기 머신) 스테이징 Prometheus 로 터널
ssh -N -L 9091:127.0.0.1:9091 staginghost &

K6_PROMETHEUS_RW_SERVER_URL=http://localhost:9091/api/v1/write \
K6_PROMETHEUS_RW_TREND_STATS="p(95),p(99),avg,max" \
K6_PROMETHEUS_RW_STALE_MARKERS=true \
k6 run -o experimental-prometheus-rw --tag testid=2026-11-10-load loadtest/<시나리오>.js
# 로컬 스택이면 URL 만 http://localhost:9090/api/v1/write
```

- `K6_PROMETHEUS_RW_TREND_STATS` 가 없으면 기본값 `p(99)` 만 전송돼 대시보드의 p95 패널이 빈다.
  지정한 통계가 `k6_<trend>_<stat>` 이름이 된다: `k6_http_req_duration_p95`, `_p99`, `_avg`, `_max` (단위 초).
  그 밖의 지표: `k6_vus`, `k6_vus_max`, `k6_http_reqs_total`, `k6_http_req_failed_rate`, `k6_checks_rate`, `k6_iterations_total`
- `--tag testid=...` 로 실행마다 이름을 붙이면 부하테스트 대시보드 상단 `testid` 변수로 골라 본다
- 요청엔 `tags: { name: '상품목록' }` 을 붙인다 — 안 붙이면 URL(쿼리·ID 포함)마다 시계열이 생겨 폭발
- `STALE_MARKERS=true`: 테스트 종료 시 VU 선이 바로 끊긴다 (없으면 5분간 마지막 값 유지)

## 7. 부하테스트 중 볼 것 — "Rekle 부하테스트" 대시보드

k6 지표와 서버 지표가 같은 시간축에 있다. 위에서 아래로:

1. **VU · k6 RPS · 실패율** — VU 를 올렸는데 RPS 가 더 안 오르면 포화점. 실패율이 thresholds(1%) 를 넘는 시점 기록
2. **k6 p95 vs 서버 p95** — 서버 p95 는 낮은데 k6 p95 만 높다 → 앱 밖(nginx·네트워크·커넥션 수립) 병목. 둘 다 높다 → 앱 안
3. **처리 중 요청 수** — VU 가 일정한데 계속 상승하면 처리량 < 유입
4. **이벤트 루프 지연 p99** — 로그인 비중을 늘릴 때 같이 오르면 bcrypt 블로킹 (O8-1)
5. **DB 풀 사용 중 · 대기 p95 · 타임아웃** — 사용 중이 `워커×(pool_size+max_overflow)` 에 붙고 대기가 늘면 풀/쿼리 병목 (O8-2). 타임아웃 > 0 이면 503
6. **외부 호출 p95** — Redis·S3·토스 지연이 요청 지연으로 번지는지
7. **컨테이너 CPU·메모리** (cAdvisor) — 앱 CPU 가 코어 수에 붙으면 워커 증설 검토(O8-6). 소크 테스트에선 메모리 우상향 = 누수
8. **Postgres 커넥션 · Redis ops**, "Rekle 인프라" 대시보드의 **데드락**(정합성 시나리오에서 0 이어야 함)·락 대기·캐시 적중률

결과는 `docs/perf/YYYY-MM-DD-<이름>.md` 에 기록 (O7-7). Grafana 패널 → Share → 시간 범위 고정 링크/스크린샷.

## 8. 대시보드

| 대시보드 | 내용 | 데이터 |
|---|---|---|
| Rekle 서비스 | HTTP·결제·비즈니스·런타임·DB 풀·외부 호출 | 앱 `/metrics` (로컬·운영) |
| Rekle 부하테스트 | k6 + 서버 + 자원 한 화면 | k6 remote write + 앱 + cAdvisor |
| Rekle 인프라 | 호스트·컨테이너·Postgres·Redis | exporter (운영형 스택만) |

커뮤니티 대시보드가 더 필요하면 Grafana → Dashboards → Import 에서 ID 로 가져온다 (UI 저장은 Grafana DB 에 남음):
Node Exporter Full `1860`, cAdvisor `14282`, PostgreSQL `9628`, Redis `763`. 데이터소스는 `Prometheus` 선택.

## 9. 로컬(Mac Docker Desktop)에서 운영형 스택 돌려 보기 — 제약

```bash
cd infra/monitoring/prod && cp .env.example .env   # 값 채우기 + REKLE_APP_NETWORK=rekle_backend_default
docker network create rekit_edge                   # 없으면 (또는 EDGE_NETWORK 를 기존 네트워크로)
docker compose up -d                                # 로컬 스택(9090/3000)과 포트가 달라 동시에 떠도 됨
```

- **node_exporter**: `/:/host:ro,rslave` 마운트가 Docker Desktop 에서 거부된다 (`path / is mounted on / but it is not a shared or slave mount`)
  → 로컬에선 override 파일로 `- /:/host:ro` 로 바꿔서 띄운다. 값은 Mac 이 아닌 Docker VM 기준
- **cAdvisor**: Docker Desktop 에선 `/var/run` 이 VM 경로로 매핑되지 않아 docker factory 등록 실패 →
  override 로 `- /var/run/docker.sock:/var/run/docker.sock:ro` 추가해도 컨테이너별 시계열(`name` 라벨)이 안 나온다. Linux 서버에선 정상
- rekle-app 컨테이너가 없으면 `RekleAppDown` 이 발화한다 (정상)
- 정리: `docker compose -p rekle-monitoring down -v`
