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

    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str
    database_pool_size: int = 5
    database_max_overflow: int = 10

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    refresh_token_remember_days: int = 30

    # Redis
    redis_url: str = "redis://localhost:6379/0"

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

    # 문의 알림 수신 이메일. None 이면 email_from 으로 fallback.
    help_admin_email: str | None = None

    # ── 결제 PG ───────────────────────────────────────────
    toss_secret_key: str | None = None
    # True 로 설정하면 TossPaymentGateway 대신 FakePaymentGateway 를 사용.
    # 로컬/개발 환경 전용. 운영(production)에서는 반드시 False.
    use_fake_pg: bool = False

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
    def effective_admin_email(self) -> str | None:
        """문의 알림 수신 이메일. help_admin_email > email_from 순으로 fallback."""
        return self.help_admin_email or self.email_from


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
