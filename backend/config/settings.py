"""
BATUHAN — Environment & Config Management (T4)
All settings loaded from environment variables. Never hardcode secrets.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -----------------------------------------------------------------------
    # Anthropic / Claude
    # -----------------------------------------------------------------------
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-5"  # Claude Sonnet 4.6 Extended
    claude_max_tokens: int = 8192
    claude_temperature: float = 0.2  # Low temp for factual audit writing

    # -----------------------------------------------------------------------
    # Application
    # -----------------------------------------------------------------------
    app_name: str = "BATUHAN"
    app_version: str = "1.0.0"
    debug: bool = False
    internal_api_key: str = "change-me-in-production"
    # CORS — comma-separated in env: ALLOWED_ORIGINS=http://a.com,http://b.com
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    log_level: str = "INFO"

    @property
    def allowed_origins_list(self) -> list[str]:
        """Return ALLOWED_ORIGINS as a list, stripping whitespace."""
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    # -----------------------------------------------------------------------
    # File Storage
    # -----------------------------------------------------------------------
    storage_backend: str = "local"          # "local" | "s3"
    storage_base_path: str = "./storage"    # local base path
    s3_bucket: str = ""
    s3_region: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # -----------------------------------------------------------------------
    # Database
    # -----------------------------------------------------------------------
    database_url: str = "sqlite:///./batuhan.db"

    # -----------------------------------------------------------------------
    # Redis / Celery
    # -----------------------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # -----------------------------------------------------------------------
    # Pipeline
    # -----------------------------------------------------------------------
    max_retries_per_step: int = 2
    step_timeout_seconds: int = 600         # 10 min per step max
    prompt_version: str = "1.0"            # bump when prompts change

    # -----------------------------------------------------------------------
    # Prompts
    # -----------------------------------------------------------------------
    prompts_dir: str = "./prompts"


@lru_cache()
def get_settings() -> Settings:
    """Return cached settings instance. Call this everywhere."""
    return Settings()

