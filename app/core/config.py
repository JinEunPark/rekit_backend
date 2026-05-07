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


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
