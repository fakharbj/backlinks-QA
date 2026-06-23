"""Crawler data contracts (framework-free dataclasses).

``CrawlArtifact`` is the single object handed to the QA engine. It carries
everything ~150 checks could need: transport outcome, the full redirect chain,
parsed page signals, every candidate link, robots evaluation, and detection
flags — plus the *expected* contract fields so checks can compare observed vs.
expected without re-reading the database.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone


class FetchError(str, enum.Enum):
    """Mutually-exclusive transport failure classes (maps to NET-* checks)."""

    NONE = "none"
    DNS = "dns"                  # NET-01
    TIMEOUT = "timeout"          # NET-02
    SSL = "ssl"                  # NET-03 / NET-04
    CONNECTION = "connection"    # NET-05 (reset/refused)
    TOO_LARGE = "too_large"      # response-size cap tripped
    BLOCKED_SSRF = "blocked_ssrf"
    BLOCKED_ROBOTS = "blocked_robots"
    REDIRECT_LOOP = "redirect_loop"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    UNKNOWN = "unknown"          # NET-06


class CrawlMode(str, enum.Enum):
    RAW = "raw"
    RENDERED = "rendered"


@dataclass(slots=True)
class RedirectHop:
    url: str
    status: int
    location: str | None = None


@dataclass(slots=True)
class RobotsDirectives:
    """Parsed meta-robots or X-Robots-Tag directive set (most-restrictive wins)."""

    raw: str = ""
    index: bool = True
    follow: bool = True
    noarchive: bool = False
    nosnippet: bool = False
    none: bool = False
    unavailable_after: datetime | None = None
    ua_specific: dict[str, str] = field(default_factory=dict)  # {"googlebot": "noindex"}
    conflicting: bool = False

    @property
    def noindex(self) -> bool:
        return self.none or not self.index

    @property
    def nofollow(self) -> bool:
        return self.none or not self.follow


@dataclass(slots=True)
class RobotsResult:
    fetched: bool = False
    parse_error: bool = False
    source_allowed: bool | None = None
    target_allowed: bool | None = None
    canonical_allowed: bool | None = None
    crawl_delay: float | None = None
    sitemaps: list[str] = field(default_factory=list)
    matched_user_agent: str | None = None


@dataclass(slots=True)
class ParsedLink:
    """A candidate outbound link found on the source page."""

    href: str                         # raw href as written
    resolved_url: str                 # absolute, resolved against base/final url
    normalized_url: str               # normalized form for matching
    anchor_text: str = ""
    image_alt: str | None = None
    rel: list[str] = field(default_factory=list)
    region: str = "body"              # header/nav/sidebar/footer/body
    in_comment: bool = False
    in_iframe: bool = False
    in_noscript: bool = False
    css_hidden: bool = False
    sponsored_block: bool = False
    ugc_block: bool = False
    context_text: str = ""            # surrounding text for relevance review
    source_mode: CrawlMode = CrawlMode.RAW  # where it was discovered

    @property
    def is_image_anchor(self) -> bool:
        return not self.anchor_text.strip() and self.image_alt is not None

    @property
    def effective_anchor(self) -> str:
        return self.anchor_text.strip() or (self.image_alt or "").strip()


@dataclass(slots=True)
class PageSignals:
    """PQ-* page-quality signals."""

    title: str | None = None
    meta_description: str | None = None
    h1: str | None = None
    word_count: int = 0
    language: str | None = None
    page_bytes: int = 0
    internal_link_count: int = 0
    external_link_count: int = 0
    outbound_link_count: int = 0
    load_time_ms: int | None = None
    spam_keyword_hits: list[str] = field(default_factory=list)
    # Posted/published date discovered on the page (JSON-LD, meta, or <time>).
    published_date: str | None = None
    modified_date: str | None = None
    date_source: str | None = None  # where we found it (for transparency)


@dataclass(slots=True)
class DetectionFlags:
    """BOT-* / soft-404 detection."""

    captcha: bool = False
    cloudflare_challenge: bool = False
    waf_block: bool = False
    soft_404: bool = False
    empty_page: bool = False
    parked: bool = False
    signature: str | None = None  # what tripped detection (for evidence)


@dataclass(slots=True)
class CrawlRequest:
    """Input to the engine: one backlink to verify, with its contract fields."""

    source_url: str
    target_url: str
    expected_target_url: str | None = None
    expected_anchor_text: str | None = None
    expected_rel: str = "dofollow"
    backlink_id: str | None = None
    # Policy
    treat_sponsored_as_follow: bool = True
    trailing_slash_policy: str = "lenient"
    respect_robots: bool = True
    use_googlebot_ua: bool = False
    allow_render: bool = True


@dataclass(slots=True)
class CrawlArtifact:
    """Everything the QA engine needs to render a verdict for one backlink."""

    request: CrawlRequest

    # ── Transport ────────────────────────────────────────────────────────────
    fetch_error: FetchError = FetchError.NONE
    fetch_error_detail: str | None = None
    http_status: int | None = None
    final_url: str | None = None
    redirect_chain: list[RedirectHop] = field(default_factory=list)
    content_type: str | None = None
    content_length: int | None = None
    encoding: str | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    tls_valid: bool | None = None
    crawl_mode: CrawlMode = CrawlMode.RAW
    crawl_duration_ms: int | None = None
    egress: str = "direct"  # "direct" or "proxy" — which path produced this result

    # ── Parsed page ──────────────────────────────────────────────────────────
    meta_robots: RobotsDirectives = field(default_factory=RobotsDirectives)
    x_robots: RobotsDirectives = field(default_factory=RobotsDirectives)
    canonical_url: str | None = None
    canonical_resolved: str | None = None
    canonical_status: int | None = None      # if secondarily fetched
    canonical_count: int = 0
    base_href: str | None = None
    robots: RobotsResult = field(default_factory=RobotsResult)
    signals: PageSignals = field(default_factory=PageSignals)
    detection: DetectionFlags = field(default_factory=DetectionFlags)

    # ── Links ────────────────────────────────────────────────────────────────
    all_links: list[ParsedLink] = field(default_factory=list)
    matched_links: list[ParsedLink] = field(default_factory=list)
    found_in_raw: bool = False
    found_in_rendered: bool = False
    rendered: bool = False
    # Set when a render WOULD help (link absent + JS-likely) but no browser was
    # attached — signals the HTTP pool to enqueue a render-pool task (Arch §6).
    render_recommended: bool = False

    # ── Object-storage pointers (filled by the worker, not the engine) ───────
    raw_html_key: str | None = None
    rendered_html_key: str | None = None
    # Transient HTML bodies the worker uploads to object storage then discards.
    # Not persisted to Postgres (kept off the DB to stay lean at 1M+; Arch §10).
    raw_html: str | None = None
    rendered_html: str | None = None

    crawled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Convenience -------------------------------------------------------------
    @property
    def primary_link(self) -> ParsedLink | None:
        return self.matched_links[0] if self.matched_links else None

    @property
    def link_found(self) -> bool:
        return bool(self.matched_links)

    @property
    def is_html(self) -> bool:
        ct = (self.content_type or "").lower()
        return "html" in ct or ct == ""

    @property
    def redirect_count(self) -> int:
        return len(self.redirect_chain)
