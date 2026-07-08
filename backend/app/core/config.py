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
    # "local" stores blobs on the worker/API filesystem under STORAGE_DIR (reliable
    # on a single host, no MinIO needed); "s3" uses the S3/MinIO settings above.
    STORAGE_BACKEND: Literal["s3", "local"] = "local"
    STORAGE_DIR: str = "var/storage"

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
    # A real browser User-Agent by default: many sites/WAFs return 403 to obvious
    # bot agents even when the page is live for real visitors. We identify as a
    # current Chrome build so a normal fetch matches what a human browser sees.
    CRAWL_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    CRAWL_GOOGLEBOT_UA: str = (
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    )
    # When a fetch is blocked (403/429/503) we retry the page once with this
    # fallback agent (Googlebot) — many publishers allow-list it. Set False to
    # disable the second attempt.
    CRAWL_BLOCK_RETRY: bool = True
    # Try the secure (https://) URL first for any http:// source. Modern browsers
    # do this (HTTPS-first), it skips the http→https redirect hop, and plain-HTTP
    # requests are more likely to be met with a bot challenge. Falls back to the
    # original http:// URL if https can't be reached.
    CRAWL_HTTPS_FIRST: bool = True
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

    # ── Proxy egress (IPRoyal Web Unblocker) ─────────────────────────────────
    # Normal crawl first; route through the proxy only when a page is blocked
    # (PROXY_MODE=escalate). "always" proxies every request; "off" disables it.
    # Credentials come from env ONLY — never commit them.
    PROXY_ENABLED: bool = False
    PROXY_MODE: Literal["off", "escalate", "always"] = "escalate"
    PROXY_PROVIDER: str = "iproyal"
    IPROYAL_PROXY_HOST: str | None = None
    IPROYAL_PROXY_PORT: int = 12323
    IPROYAL_PROXY_USERNAME: str | None = None
    IPROYAL_PROXY_PASSWORD: str | None = None
    # The Web Unblocker terminates TLS (MITM), so certificate verification must be
    # OFF for proxied requests — this mirrors the `-k` flag in IPRoyal's curl docs.
    PROXY_VERIFY_TLS: bool = False
    # The unblocker is slower (it retries/renders server-side) → a longer timeout.
    PROXY_TIMEOUT: float = 90.0
    # Extra headers added to every proxied request, as JSON in .env. Use this to
    # turn on the provider's JavaScript rendering for SPA pages whose link is drawn
    # client-side (e.g. IPRoyal: PROXY_HEADERS={"X-Render":"true"} — confirm the
    # exact header in their docs). Empty by default.
    PROXY_HEADERS: dict[str, str] = Field(default_factory=dict)
    # Re-fetch a page through the proxy when the backlink is absent from the raw
    # HTML and the page looks JavaScript-driven (the proxy can render JS).
    PROXY_RENDER_ON_JS_MISSING: bool = True

    # ── Render escalation (Playwright) ───────────────────────────────────────
    # Off by default: the headless browser pool (Playwright) is an optional add-on
    # and is not installed on the standard single-node deployment. With it off,
    # every link still gets a full raw-HTTP verdict and fires alerts immediately
    # instead of waiting on a render worker that may not exist.
    RENDER_ENABLED: bool = False
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

    # ── Spam-neighborhood keyword scan (PQ-06) ───────────────────────────────
    # Historically PQ-06 substring-matched a fixed keyword tuple over the WHOLE
    # page text, firing inside legit words (porn⊂popcorn, casino⊂casinos) and on
    # nav/footer ad blocks — a silent −10 pts. It is now a word-boundary scan
    # scoped to main content by default, with these tunables:
    QA_SPAM_ENABLED: bool = True          # master switch for the PQ-06 scan
    # Which regions count toward the PQ-06 gate: "content" = only main content /
    # link anchor / link context (boilerplate hits are downgraded to LOW);
    # "page" = any region can trip the MEDIUM issue (legacy-ish behavior).
    QA_SPAM_SCOPE: Literal["content", "page"] = "content"
    QA_SPAM_MIN_HITS: int = 1             # in-scope hits required to fire MEDIUM
    # Extra phrases appended to the default spam corpus (category "other").
    QA_SPAM_EXTRA_KEYWORDS: list[str] = []
    # Phrases to drop from the corpus / suppress as hits (case-insensitive).
    QA_SPAM_ALLOWLIST: list[str] = []

    # ── Metric-band cutoffs (scoring signals) ────────────────────────────────
    # The scorer's DA / Semrush-AS / domain-age band signals (source_da_band,
    # semrush_as_band, domain_age_band) are computed from the source domain's
    # stored metrics using these thresholds, so agencies can retune the bands
    # without a redeploy. A metric >= HIGH → "high", >= MEDIUM → "medium", else
    # "low"; a missing metric emits no signal at all (not "unknown"). These only
    # affect the score when a rule set assigns points to those band outcomes
    # (all default to 0 → no score change out of the box).
    SCORE_DA_HIGH: int = 60     # Moz DA >= this → "high"
    SCORE_DA_MEDIUM: int = 30   # Moz DA >= this → "medium" (else "low")
    SCORE_AS_HIGH: int = 50     # Semrush AS >= this → "high"
    SCORE_AS_MEDIUM: int = 25   # Semrush AS >= this → "medium" (else "low")
    SCORE_AGE_OLD_DAYS: int = 1825    # domain age >= this (5y) → "old"
    SCORE_AGE_MEDIUM_DAYS: int = 365  # domain age >= this (1y) → "medium" (else "new")

    # ── Analytics KPI thresholds ──────────────────────────────────────────────
    # A source domain whose Moz Spam Score is >= this is counted as "spam" in the
    # Analytics/Dashboard KPI boxes (source_domains.spam_score, 0–100 scale).
    ANALYTICS_SPAM_THRESHOLD: int = 30

    # ── Access control (Phase 9) ─────────────────────────────────────────────
    # Open self-signup. False (default) = once the first workspace exists, only
    # admins create accounts (Team desk); the very first registration always
    # works so a fresh install can bootstrap itself.
    ALLOW_PUBLIC_REGISTRATION: bool = False

    # ── Scheduling / batching ────────────────────────────────────────────────
    CRAWL_BATCH_SIZE_HTTP: int = 100
    CRAWL_BATCH_SIZE_RENDER: int = 20
    DEFAULT_RECHECK_INTERVAL_HOURS: int = 24
    # A crawl/recheck job (and its ops batch) is finalized only when its tasks all
    # report back (processed >= total). If some Celery tasks are lost (worker
    # recycle/OOM, time-limit kill), the job — and the batch mirroring it — hang in
    # 'running' forever. `reconcile_stale_crawl_jobs` (beat, every 5 min) closes out
    # any PENDING/RUNNING job with no progress for this many minutes. 20 min is well
    # beyond the 600s task hard limit + render-batch runtime, so it can't race a
    # live task; raise it if healthy-but-backlogged jobs get finalized early.
    CRAWL_JOB_STALE_MINUTES: int = 20

    # ── Retention (days) ─────────────────────────────────────────────────────
    RETENTION_HISTORY_DAYS: int = 365
    RETENTION_SNAPSHOT_DAYS: int = 30
    RETENTION_AUDIT_DAYS: int = 730

    # ── Source-site metrics (Similarweb / Moz via RapidAPI) ───────────────────
    # Authority/traffic metrics for the SOURCE domain of each backlink. These come
    # from an external API (they can't be crawled) and are cached per domain for
    # SITE_METRICS_CACHE_DAYS. Off by default → the column shows "—" until set.
    SITE_METRICS_ENABLED: bool = False
    #  • "similarweb"   — Similarweb Insights on RapidAPI (global rank + traffic).
    #  • "moz_rapidapi" — a "Moz DA PA" RapidAPI proxy (DA + PA).
    #  • "moz_official" — Moz's own Links API (DA + PA + Spam Score).
    SITE_METRICS_PROVIDER: Literal["similarweb", "moz_rapidapi", "moz_official"] = "similarweb"
    SITE_METRICS_CACHE_DAYS: int = 30
    SITE_METRICS_TIMEOUT_SECONDS: float = 15.0

    # RapidAPI key — shared by the similarweb + moz_rapidapi providers.
    RAPIDAPI_KEY: str | None = None

    # Similarweb Insights (RapidAPI): GET {endpoint}?domain=<domain>
    SIMILARWEB_HOST: str = "similarweb-insights.p.rapidapi.com"
    SIMILARWEB_ENDPOINT: str = "https://similarweb-insights.p.rapidapi.com/traffic"

    # Moz DA/PA (RapidAPI): POST {endpoint} with {"q": <domain>}
    MOZ_RAPIDAPI_HOST: str = "moz-da-pa1.p.rapidapi.com"
    MOZ_RAPIDAPI_ENDPOINT: str = "https://moz-da-pa1.p.rapidapi.com/v1/getDaPa"

    # Moz official Links API: POST {endpoint} with {"targets": [<domain>]}
    MOZ_ACCESS_ID: str | None = None
    MOZ_SECRET_KEY: str | None = None
    MOZ_API_TOKEN: str | None = None
    MOZ_API_ENDPOINT: str = "https://lsapi.seomoz.com/v2/url_metrics"

    # ── Per-domain metrics (Phase 8: Moz DA/PA · Semrush · domain age) ────────
    # Fetched per SOURCE MAIN DOMAIN, stored in source_domains (no Redis), refreshed
    # on a cadence. Domain age uses free RDAP (no key); Moz/Semrush need RAPIDAPI_KEY.
    # Semrush via RapidAPI (Authority Score / monthly traffic / # keywords).
    SEMRUSH_RAPIDAPI_HOST: str = "semrush-api6.p.rapidapi.com"
    SEMRUSH_RAPIDAPI_ENDPOINT: str | None = None  # set the domain-overview endpoint URL
    # Domain age via RDAP (free, no key). rdap.org bootstraps to the right registry.
    DOMAIN_AGE_ENABLED: bool = True
    DOMAIN_AGE_RDAP_ENDPOINT: str = "https://rdap.org/domain/"
    DOMAIN_METRICS_REFRESH_DAYS: int = 30   # only refetch a domain this often
    DOMAIN_METRICS_BATCH_LIMIT: int = 15    # domains processed per fetch trigger
    DOMAIN_METRICS_TIMEOUT_SECONDS: float = 8.0
    # Review batches (0029): domain-import metric checks run inline in the
    # request (like /source-domains/fetch-metrics) — this caps domains per call
    # so the request stays snappy; the UI keeps calling until none remain.
    BATCH_DOMAIN_CHECK_CAP: int = 25
    # Staged QA checks are chunked onto the "qa" queue this many links per task.
    BATCH_QA_CHUNK_SIZE: int = 10

    # ── Google Sheets (ingest + write-back) ──────────────────────────────────
    # One global main sheet lists projects (Project Name + Project Sheet URL); each
    # project sheet is synced into the system. Auth is a Google service account —
    # share the sheets with the service-account email. Credentials come from env.
    GOOGLE_SHEETS_ENABLED: bool = False
    GOOGLE_SA_JSON_BASE64: str | None = None   # base64 of the service-account JSON
    GOOGLE_SA_JSON_FILE: str | None = None     # or a path to the JSON file
    GOOGLE_MAIN_SHEET_ID: str | None = None    # spreadsheet ID of the global main sheet
    GOOGLE_MAIN_SHEET_TAB: str | None = None   # tab name (None → first worksheet)
    GOOGLE_MAIN_PROJECT_COL: str = "Project Name"     # main-sheet column: project name
    GOOGLE_MAIN_URL_COL: str = "Project Sheet URL"    # main-sheet column: project sheet link
    # Spread the per-project syncs so 1,000 sheets don't hammer the Sheets API at once.
    GOOGLE_SYNC_STAGGER_SECONDS: float = 2.0
    GOOGLE_SHEETS_TIMEOUT_SECONDS: float = 60.0
    # Google Sheets read-quota guard. Google caps read requests at ~300/min per
    # project; we hard-cap OUR reads well under it via a shared Redis
    # token-per-second bucket, so a big multi-project / multi-tab sync can never
    # trip the quota (excess reads simply wait their turn). 0 disables the cap.
    GOOGLE_SHEETS_READS_PER_MIN: int = 250
    # Sync project sheets ONE AT A TIME (a Celery chain) instead of dispatching all
    # of them at once — each project finishes before the next starts, so the API
    # isn't hit by every project simultaneously. False → legacy staggered fan-out.
    GOOGLE_SHEETS_SEQUENTIAL_SYNC: bool = True
    # Short-lived cache (Redis) of raw sheet reads (tab list + per-tab values),
    # SHARED by the mapping preview and the import sync. The map→sync flow reads
    # the mapping preview first; the import then reuses that exact read instead of
    # fetching the tab a second time — one Google request per tab, and the import
    # matches what you previewed. Cleared on write-back. 0 disables (always fresh).
    GOOGLE_SHEETS_READ_CACHE_SECONDS: int = 600
    # Auto-create an app account (Viewer role, scoped to that project) for every
    # sheet "User" name that has no catalog mapping yet; admins hand out access
    # via Team → Reset password. Off → sheets never touch the user table.
    SHEETS_AUTO_CREATE_USERS: bool = True
    # QA/stat checks are MANUAL by default: imports/syncs leave new links as
    # "QA pending" until someone starts a check from the Backlinks list. Turning
    # this on restores check-immediately-after-import (crawls + API credits).
    AUTO_QA_ON_IMPORT: bool = False

    # ── Index checking (Google site: via the proxy) ──────────────────────────
    # Checks whether the EXACT source URL is indexed by Google (site:<url>). Routed
    # through the IPRoyal proxy (Google blocks datacenter IPs). Deduped by source
    # URL and re-checked at most every INDEX_RECHECK_DAYS. Failures → UNCERTAIN,
    # never a false "not indexed".
    INDEX_CHECK_ENABLED: bool = True
    INDEX_RECHECK_DAYS: int = 7
    INDEX_STAGGER_SECONDS: float = 6.0     # delay between checks (anti-block)
    INDEX_BATCH_LIMIT: int = 500           # max source URLs per dispatch
    INDEX_TIMEOUT_SECONDS: float = 45.0
    # Provider:
    #  • "serper"       — serper.dev Google Search API (reliable JSON, free 2,500
    #    queries). RECOMMENDED. Needs SERPER_API_KEY.
    #  • "google_cse"   — Google Custom Search JSON API. Note: Google deprecated
    #    "Search the entire web" for new engines, so this only works for engines that
    #    had it enabled previously. Needs GOOGLE_CSE_API_KEY + _CX.
    #  • "proxy_scrape" — scrape google.com/search via the proxy (unreliable; Google
    #    now serves a JS-only shell, so most results come back UNCERTAIN).
    SERP_PROVIDER: Literal["serper", "google_cse", "proxy_scrape"] = "proxy_scrape"
    SERPER_API_KEY: str | None = None
    GOOGLE_CSE_API_KEY: str | None = None
    GOOGLE_CSE_CX: str | None = None       # Programmable Search Engine ID
    INDEX_GOOGLE_ENDPOINT: str = "https://www.google.com/search"  # proxy_scrape only

    # ── Integrations ─────────────────────────────────────────────────────────
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str = "alerts@linksentinel.example"
    SMTP_USE_TLS: bool = True

    # ── Built-in alerting (zero-config) ──────────────────────────────────────
    # Out of the box — without anyone creating an alert rule — the system raises
    # an in-app alert whenever a backlink is broken, removed, or errors, and
    # emails the team if SMTP is configured. While a link stays broken it
    # re-alerts every ALERT_RENOTIFY_HOURS (not on every scan) so the team gets a
    # reminder without being spammed. It also sends one "recovered" note when a
    # previously broken link comes back.
    ALERT_DEFAULT_ENABLED: bool = True
    # Who receives the built-in emails. Leave empty to fall back to every active
    # member of the link's workspace. Accepts a comma-separated string in .env.
    ALERT_DEFAULT_EMAILS: list[str] = Field(default_factory=list)
    ALERT_RENOTIFY_HOURS: int = 24

    # ── Observability ────────────────────────────────────────────────────────
    SENTRY_DSN: str | None = None
    PROMETHEUS_ENABLED: bool = True

    @field_validator("CORS_ORIGINS", "ALERT_DEFAULT_EMAILS", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
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
