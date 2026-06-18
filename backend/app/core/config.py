"""Typed application settings (12-factor, Pydantic v2 ``BaseSettings``).

Every tunable in the system lives here so that behaviour is reproducible and
auditable. Nothing reads ``os.environ`` directly anywhere else in the codebase.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Runtime ──────────────────────────────────────────────────────────────
    ENVIRONMENT: Literal["dev", "staging", "prod", "test"] = "dev"
    DEBUG: bool = False
    SERVICE_NAME: str = "linksentinel-api"
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # ── API ──────────────────────────────────────────────────────────────────
    API_V1_PREFIX: str = "/api/v1"
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    DOCS_ENABLED: bool = True

    # ── Postgres ─────────────────────────────────────────────────────────────
    # Writes go to the primary; read-only endpoints may use a replica DSN.
    DATABASE_URL: PostgresDsn = Field(
        default="postgresql+asyncpg://linksentinel:linksentinel@pgbouncer:6432/linksentinel"  # noqa: E501
    )
    DATABASE_REPLICA_URL: PostgresDsn | None = None
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_ECHO: bool = False
    # PgBouncer runs in *transaction* pooling mode, which is incompatible with
    # server-side prepared statements. Disable them when pooled.
    DB_USE_PGBOUNCER: bool = True

    # ── Redis / Celery ───────────────────────────────────────────────────────
    REDIS_URL: RedisDsn = Field(default="redis://redis:6379/0")
    CELERY_BROKER_URL: RedisDsn = Field(default="redis://redis:6379/1")
    CELERY_RESULT_BACKEND: RedisDsn = Field(default="redis://redis:6379/2")
    CRAWL_QUEUE_SHARDS: int = 4  # number of crawl.http.<n> shards

    # ── Object storage (S3 / MinIO) ──────────────────────────────────────────
    S3_ENDPOINT_URL: str | None = "http://minio:9000"
    S3_REGION: str = "us-east-1"
    S3_ACCESS_KEY: str = "linksentinel"
    S3_SECRET_KEY: str = "linksentinel-secret"
    S3_BUCKET_SNAPSHOTS: str = "ls-snapshots"
    S3_BUCKET_REPORTS: str = "ls-reports"
    S3_BUCKET_IMPORTS: str = "ls-imports"
    S3_FORCE_PATH_STYLE: bool = True  # required by MinIO
    SIGNED_URL_TTL_SECONDS: int = 600

    # ── Auth / JWT ───────────────────────────────────────────────────────────
    JWT_SECRET: str = Field(default="change-me-in-prod-please-32-chars-min")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MINUTES: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 7
    PASSWORD_RESET_TTL_MINUTES: int = 30
    LOGIN_MAX_FAILED_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15
    # Envelope-encryption key for integration secrets (Slack/SMTP creds, etc.).
    # In prod this is sourced from a KMS/Secrets-Manager; dev uses this default.
    SECRETS_ENCRYPTION_KEY: str = Field(default="dev-only-fernet-key-32bytes-base64==")

    # ── Crawler defaults ─────────────────────────────────────────────────────
    CRAWL_USER_AGENT: str = (
        "LinkSentinelBot/1.0 (+https://linksentinel.example/bot; "
        "backlink QA; contact: ops@linksentinel.example)"
    )
    CRAWL_GOOGLEBOT_UA: str = (
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    )
    CRAWL_CONNECT_TIMEOUT: float = 10.0
    CRAWL_READ_TIMEOUT: float = 20.0
    CRAWL_TOTAL_TIMEOUT: float = 35.0
    CRAWL_MAX_REDIRECTS: int = 10
    CRAWL_REDIRECT_WARN_THRESHOLD: int = 3
    CRAWL_MAX_RESPONSE_BYTES: int = 8 * 1024 * 1024  # 8 MiB hard cap
    CRAWL_MAX_RETRIES: int = 3
    CRAWL_GLOBAL_CONCURRENCY: int = 200
    CRAWL_PER_DOMAIN_CONCURRENCY: int = 2
    CRAWL_DEFAULT_RATE_PER_SEC: float = 1.0  # token-bucket refill per domain
    CRAWL_DEFAULT_BURST: int = 2
    CRAWL_RESPECT_ROBOTS: bool = True
    ROBOTS_CACHE_TTL_SECONDS: int = 24 * 3600
    CIRCUIT_BREAKER_FAILS: int = 8
    CIRCUIT_BREAKER_COOLDOWN_SECONDS: int = 900

    # ── Render escalation (Playwright) ───────────────────────────────────────
    RENDER_ENABLED: bool = True
    RENDER_TIMEOUT_MS: int = 20_000
    RENDER_WAIT_UNTIL: Literal["load", "domcontentloaded", "networkidle"] = "networkidle"
    # Escalate to a headless render only when the link is absent in raw HTML AND
    # the page looks JS-driven below these heuristics.
    RENDER_MIN_TEXT_RATIO: float = 0.10  # text bytes / total bytes
    RENDER_SCRIPT_HEAVY_RATIO: float = 0.55  # script bytes / total bytes

    # ── QA policy defaults ───────────────────────────────────────────────────
    QA_THIN_CONTENT_WORDS: int = 250
    QA_EXCESSIVE_OUTBOUND_LINKS: int = 100
    QA_TREAT_SPONSORED_AS_FOLLOW: bool = True  # paid-campaign default
    QA_TRAILING_SLASH_POLICY: Literal["strict", "lenient"] = "lenient"

    # ── Scheduling / batching ────────────────────────────────────────────────
    CRAWL_BATCH_SIZE_HTTP: int = 100
    CRAWL_BATCH_SIZE_RENDER: int = 20
    DEFAULT_RECHECK_INTERVAL_HOURS: int = 24

    # ── Retention (days) ─────────────────────────────────────────────────────
    RETENTION_HISTORY_DAYS: int = 365
    RETENTION_SNAPSHOT_DAYS: int = 30
    RETENTION_AUDIT_DAYS: int = 730

    # ── Integrations ─────────────────────────────────────────────────────────
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str = "alerts@linksentinel.example"
    SMTP_USE_TLS: bool = True

    # ── Observability ────────────────────────────────────────────────────────
    SENTRY_DSN: str | None = None
    PROMETHEUS_ENABLED: bool = True

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors(cls, v: object) -> object:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @model_validator(mode="after")
    def _guard_prod_secrets(self) -> "Settings":
        if self.ENVIRONMENT == "prod":
            if self.JWT_SECRET.startswith("change-me"):
                raise ValueError("JWT_SECRET must be set to a strong value in prod")
            if len(self.JWT_SECRET) < 32:
                raise ValueError("JWT_SECRET must be at least 32 characters in prod")
        return self

    @property
    def sync_database_url(self) -> str:
        """psycopg/sync DSN for Alembic and Celery beat-store helpers."""
        return str(self.DATABASE_URL).replace("+asyncpg", "+psycopg2")

    @property
    def read_database_url(self) -> str:
        return str(self.DATABASE_REPLICA_URL or self.DATABASE_URL)


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — import this everywhere instead of constructing Settings."""
    return Settings()


settings = get_settings()
