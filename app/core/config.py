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

    # CORS (JSON 배열 형식)
    cors_origins: list[str] = Field(default_factory=list)

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
