from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Rekle Backend"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # 배포 이미지 태그 — compose 가 IMAGE_TAG 로 주입.
    # Sentry release 로 쓰여 어느 배포부터 에러가 났는지 추적한다
    app_version: str = "dev"

    # ── 에러 추적 (Sentry) ─────────────────────────────────
    # 비어 있으면 비활성 (로컬·테스트 기본). 운영 시크릿에 DSN 을 넣으면 켜진다
    sentry_dsn: str | None = None
    # 성능 트레이스 샘플 비율. 0 = 에러만 — 무료 플랜 트랜잭션 한도·오버헤드 때문에 기본은 끔
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str
    database_pool_size: int = 5
    database_max_overflow: int = 10
    # 풀이 꽉 찼을 때 커넥션을 기다리는 최대 시간(초). 기본 30초면 고갈 시 요청이 줄줄이 쌓인다 →
    # 짧게 끊고 503 으로 빨리 실패시킨다
    database_pool_timeout: float = Field(default=5.0, gt=0)
    # Postgres 세션 타임아웃(ms, 0 = 끔 — Postgres 자체 의미). 느린 쿼리·락 대기·트랜잭션 방치가
    # 커넥션을 무기한 점유해 풀이 마르는 것을 막는다. 앱 엔진에만 적용 (alembic 은 자체 엔진)
    database_statement_timeout_ms: int = Field(default=10_000, ge=0)
    database_idle_in_transaction_timeout_ms: int = Field(default=30_000, ge=0)

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    refresh_token_remember_days: int = 30

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    # 초 단위. 없으면 Redis 가 멈췄을 때 요청도 무기한 멈춘다
    redis_socket_timeout: float = Field(default=2.0, gt=0)
    redis_socket_connect_timeout: float = Field(default=2.0, gt=0)
    # 워커(프로세스)당 커넥션 상한. 기본 풀은 초과 시 대기하지 않고 즉시 ConnectionError
    redis_max_connections: int = Field(default=50, gt=0)

    # CORS (JSON 배열 형식)
    cors_origins: list[str] = Field(default_factory=list)

    # ── 이메일 발송 ───────────────────────────────────────
    # provider: "console" (dev mock — stdout 출력) / "gmail" (Gmail SMTP)
    # gmail 선택 시 GMAIL_USER + GMAIL_APP_PASSWORD 필수.
    email_provider: Literal["console", "gmail"] = "console"
    gmail_user: str | None = None
    gmail_app_password: str | None = None
    # 'Rekit <noreply@rekit.kr>' 형식. None 이면 gmail_user 를 발신자로 사용.
    email_from: str | None = None
    # 비밀번호 재설정 링크 등 메일 본문에 박을 프론트 base URL
    frontend_url: str = "http://localhost:5173"

    # ── 소셜 로그인 OAuth ───────────────────────────────────
    # 카카오: developers.kakao.com → 내 애플리케이션 → REST API 키 + Client Secret
    # 네이버: developers.naver.com → 애플리케이션 → Client ID + Secret
    # 구글: console.cloud.google.com → APIs & Services → OAuth 2.0 Client IDs
    # redirect_uri 는 각 PG 콘솔 설정과 정확히 일치해야 함 (스키마/포트/경로 모두)
    kakao_client_id: str | None = None
    kakao_client_secret: str | None = None
    kakao_redirect_uri: str | None = None
    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    naver_redirect_uri: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    # 소셜 신규가입용 임시 토큰 만료 (분). JWT 로 단명 발급.
    social_signup_token_expire_minutes: int = 15
    # 소셜 전용 계정 탈퇴 재인증 토큰 만료 (분). JWT 로 단명 발급.
    withdrawal_token_expire_minutes: int = 10

    # 문의 알림 수신 이메일. None 이면 email_from 으로 fallback.
    help_admin_email: str | None = None

    # ── 결제 PG (토스페이먼츠) ────────────────────────────
    # 시크릿 키(주문서형·결제창형 연동 = gsk). 서버↔토스 Basic 인증.
    # Fake 게이트웨이 제거로 결제·웹훅이 항상 실 토스를 호출 → 필수값(누락 시 부팅 실패).
    toss_secret_key: str
    # 방치된 PENDING 주문(결제창 이탈) 정리 주기(초). 0 이면 스위퍼 끔.
    pending_order_sweep_interval_seconds: int = 120

    # ── 런타임 관측 ──────────────────────────────────────
    # 이벤트 루프 지연 측정 주기(초). 0 이면 끔. 짧을수록 짧은 블로킹도 잡지만 관측치가 늘어난다
    event_loop_lag_interval_seconds: float = Field(default=0.5, ge=0)

    # ── 전화번호 인증 (Octomo) ─────────────────────────────
    octomo_api_key: str | None = None

    # S3 호환 오브젝트 스토리지 (dev: SeaweedFS)
    s3_endpoint_url: str
    s3_region: str = "ap-northeast-2"
    s3_bucket: str
    s3_access_key: str
    s3_secret_key: str
    s3_public_url_base: str
    s3_force_path_style: bool = True
    s3_presign_expire_seconds: int = 600
    s3_max_upload_size: int = 10 * 1024 * 1024  # 10MB

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def json_logs(self) -> bool:
        """development 외(staging·production)는 수집·검색용 JSON 로그."""
        return self.app_env != "development"

    @property
    def effective_admin_email(self) -> str | None:
        """문의 알림 수신 이메일. help_admin_email > email_from 순으로 fallback."""
        return self.help_admin_email or self.email_from


@lru_cache
def get_settings() -> Settings:
    # BaseSettings 필드는 .env/환경변수에서 채워짐 — Pyright 는 이를 모르고 오탐
    return Settings()  # pyright: ignore[reportCallIssue]


settings = get_settings()
