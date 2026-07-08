"""
BATUHAN — Environment & Config Management (T4)
All settings loaded from environment variables. Never hardcode secrets.
"""

from functools import lru_cache
from pydantic import field_validator
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
    claude_model: str = "claude-sonnet-4-6"  # Claude Sonnet 4.6 Extended
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
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001"
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
    s3_endpoint_url: str = ""            # Cloudflare R2: https://<ACCOUNT_ID>.r2.cloudflarestorage.com
    local_storage_cache_dir: str = "/tmp/certiva-doc-cache"  # temp cache for S3 downloads

    # -----------------------------------------------------------------------
    # Database
    # -----------------------------------------------------------------------
    database_url: str = "sqlite:///./batuhan.db"

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        # Railway/Heroku hand out "postgres://"; SQLAlchemy 2.x requires
        # "postgresql://". Rewrite so a managed Postgres URL works as-is.
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        return v


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

    # -----------------------------------------------------------------------
    # Audit Set — blank document templates
    # -----------------------------------------------------------------------
    blank_set_path: str = "./uaf_blank_set"
    # docxtpl (Jinja2) templates live here.
    # Default resolves relative to WORKDIR (/app/uaf_blank_set inside the container).
    # Override locally with BLANK_SET_PATH=/Users/batuhan/BATUHAN/uaf_blank_set\ copy
    # if you want to use the copy directly without copying into backend/.

    # -----------------------------------------------------------------------
    # Branding (set per CB deployment via environment variables)
    # -----------------------------------------------------------------------
    cb_name: str = "IFC Global LLC"
    cb_short_name: str = "IFC"
    cb_logo_url: str = ""
    cb_primary_color: str = "#1F4E79"
    cb_website: str = "https://www.ifcglobal.us"
    cb_email: str = "application@ifcglobal.us"
    cb_phone: str = ""
    cb_address: str = ""
    cb_accreditation_bodies: str = "UAF,TURKAK"
    cb_supported_standards: str = "QMS,EMS,OHSMS,FSMS,ISMS,MDQMS,ABMS,ENMS"

    @property
    def accreditation_bodies_list(self) -> list[str]:
        return [x.strip() for x in self.cb_accreditation_bodies.split(",") if x.strip()]

    @property
    def supported_standards_list(self) -> list[str]:
        return [x.strip() for x in self.cb_supported_standards.split(",") if x.strip()]

    # -----------------------------------------------------------------------
    # Auth — JWT & first-admin bootstrap
    # -----------------------------------------------------------------------
    secret_key: str = "change-this-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 8

    # Set both to bootstrap the first admin on startup (leave empty to skip).
    admin_email: str = ""
    admin_password: str = ""

    # -----------------------------------------------------------------------
    # Email (Resend)
    # -----------------------------------------------------------------------
    resend_api_key: str = ""          # Set in Railway env. Empty = email disabled (dev mode).
    email_from: str = "IFC Global <no-reply@ifcglobal.us>"
    email_base_url: str = "https://compassionate-miracle-production.up.railway.app"
    # email_base_url is used to build links inside emails (e.g. login link).
    # Override with the actual production URL once a custom domain is set.


@lru_cache()
def get_settings() -> Settings:
    """Return cached settings instance. Call this everywhere."""
    return Settings()

