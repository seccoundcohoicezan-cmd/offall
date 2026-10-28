from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "OFALL AI Gateway"
    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./dev.db"
    redis_url: str = "redis://localhost:6379/0"
    master_encryption_key: str = ""
    jwt_secret: str = ""
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    allowed_origins: str = "http://localhost:3000"
    registration_open: bool = True
    cookie_secure: bool = False

    telegram_bot_token: str = ""
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

    enable_mock_provider: bool = False

    max_message_chars: int = 20_000
    max_chats_per_user: int = 500
    max_parallel_jobs_per_user: int = 3
    job_timeout_seconds: int = 600
    key_max_concurrency: int = 4
    default_cooldown_seconds: int = 60
    rate_limit_per_minute: int = 120
    login_rate_limit_per_minute: int = 10
    stream_ttl_seconds: int = 3600
    cache_similarity_threshold: float = Field(default=0.95, ge=0.5, le=1.0)

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
