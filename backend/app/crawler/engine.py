"""Crawl orchestration — the tiered fetch pipeline (Arch §8).

``CrawlEngine`` runs one consistent pipeline whether it is verifying a single link
(live API recheck) or one of a million in a worker batch:

    normalize → robots → fetch raw → detect → parse → match link
              → (escalate to render only if absent & JS-likely) → assemble artifact

Dependency injection keeps the library framework-free:
  * ``robots_cache`` — optional async get/set (the worker wires Redis; tests omit it).
  * ``browser`` — an optional ``BrowserManager`` (only the render pool provides one).
  * ``rate_limiter`` — optional async callable enforcing the per-domain token bucket.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

import httpx

from app.crawler import detect as detect_mod
from app.crawler.fetch import FetchOutcome, build_client, fetch_raw
from app.crawler.normalize import normalize_url, registrable_domain
from app.crawler.parse import parse_html, parse_x_robots_header
from app.crawler.robots import RobotsTxt
from app.crawler.types import (
    CrawlArtifact,
    CrawlMode,
    CrawlRequest,
    FetchError,
    ParsedLink,
    RobotsResult,
)

_JS_FRAMEWORK_MARKERS = (
    "data-reactroot", "__next_data__", "ng-app", "ng-version", "v-cloak",
    "data-vue", "__nuxt__", "data-svelte", "window.__initial_state__",
    "data-server-rendered", "id=\"root\"", "id=\"app\"",
)
_ROBOTS_FETCH_TIMEOUT = 8.0


class RobotsCache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int) -> None: ...


class BrowserLike(Protocol):
    async def render(self, url: str, *, timeout_ms: int, wait_until: str) -> object: ...


@dataclass(slots=True)
class CrawlConfig:
    user_agent: str = "LinkSentinelBot/1.0 (+https://linksentinel.example/bot)"
    googlebot_ua: str = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    connect_timeout: float = 10.0
    read_timeout: float = 20.0
    total_timeout: float = 35.0
    max_redirects: int = 10
    max_bytes: int = 8 * 1024 * 1024
    respect_robots: bool = True
    robots_ttl: int = 24 * 3600
    block_retry: bool = True
    render_enabled: bool = True
    render_timeout_ms: int = 20_000
    render_wait_until: str = "networkidle"
    render_min_text_ratio: float = 0.10
    render_script_heavy_ratio: float = 0.55
    proxy: str | None = None

    @classmethod
    def from_settings(cls) -> "CrawlConfig":
        from app.core.config import settings

        return cls(
            user_agent=settings.CRAWL_USER_AGENT,
            googlebot_ua=settings.CRAWL_GOOGLEBOT_UA,
            connect_timeout=settings.CRAWL_CONNECT_TIMEOUT,
            read_timeout=settings.CRAWL_READ_TIMEOUT,
            total_timeout=settings.CRAWL_TOTAL_TIMEOUT,
            max_redirects=settings.CRAWL_MAX_REDIRECTS,
            max_bytes=settings.CRAWL_MAX_RESPONSE_BYTES,
            respect_robots=settings.CRAWL_RESPECT_ROBOTS,
            robots_ttl=settings.ROBOTS_CACHE_TTL_SECONDS,
            block_retry=settings.CRAWL_BLOCK_RETRY,
            render_enabled=settings.RENDER_ENABLED,
            render_timeout_ms=settings.RENDER_TIMEOUT_MS,
            render_wait_until=settings.RENDER_WAIT_UNTIL,
            render_min_text_ratio=settings.RENDER_MIN_TEXT_RATIO,
            render_script_heavy_ratio=settings.RENDER_SCRIPT_HEAVY_RATIO,
        )


class CrawlEngine:
    def __init__(
        self,
        config: CrawlConfig | None = None,
        *,
        robots_cache: RobotsCache | None = None,
        browser: BrowserLike | None = None,
        rate_limiter: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self.config = config or CrawlConfig()
        self._robots_cache = robots_cache
        self._browser = browser
        self._rate_limiter = rate_limiter
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "CrawlEngine":
        self._client = build_client(
            user_agent=self.config.user_agent,
            connect_timeout=self.config.connect_timeout,
            read_timeout=self.config.read_timeout,
            total_timeout=self.config.total_timeout,
            proxy=self.config.proxy,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("CrawlEngine must be used as an async context manager")
        return self._client

    # ── Public API ───────────────────────────────────────────────────────────
    async def crawl(self, request: CrawlRequest) -> CrawlArtifact:
        artifact = CrawlArtifact(request=request)
        ua = self.config.googlebot_ua if request.use_googlebot_ua else self.config.user_agent

        source = normalize_url(request.source_url)
        if not source.valid:
            artifact.fetch_error = FetchError.UNKNOWN
            artifact.fetch_error_detail = f"invalid source url: {source.error}"
            return artifact

        domain = source.registrable_domain
        if self._rate_limiter is not None:
            await self._rate_limiter(domain)

        # ── Robots gate (RBT-03) ────────────────────────────────────────────
        robots = await self._evaluate_robots(source.normalized, ua, request)
        artifact.robots = robots
        if (
            request.respect_robots
            and self.config.respect_robots
            and robots.source_allowed is False
        ):
            artifact.fetch_error = FetchError.BLOCKED_ROBOTS
            artifact.fetch_error_detail = "robots.txt disallows source page"
            return artifact

        # ── Raw fetch ────────────────────────────────────────────────────────
        outcome = await fetch_raw(
            self.client,
            source.original,
            request,
            max_redirects=self.config.max_redirects,
            max_bytes=self.config.max_bytes,
            retry_user_agent=(
                self.config.googlebot_ua
                if (self.config.block_retry and not request.use_googlebot_ua)
                else None
            ),
        )
        self._apply_fetch(artifact, outcome)
        if outcome.error in (
            FetchError.DNS, FetchError.SSL, FetchError.CONNECTION, FetchError.TIMEOUT,
            FetchError.BLOCKED_SSRF, FetchError.REDIRECT_LOOP, FetchError.TOO_MANY_REDIRECTS,
            FetchError.UNKNOWN,
        ):
            return artifact  # transport failed → QA emits the NET-*/RDR-* verdict

        # ── X-Robots-Tag (headers) ──────────────────────────────────────────
        xr_values = [v for k, v in outcome.raw_header_pairs if k.lower() == "x-robots-tag"]
        if xr_values:
            artifact.x_robots = parse_x_robots_header(xr_values)

        # Non-HTML host: record content-type, let CT-* handle it; no parsing.
        if not artifact.is_html:
            artifact.detection = detect_mod.detect(
                status=outcome.status, headers=outcome.headers, body="", signals=artifact.signals
            )
            return artifact

        # ── Parse raw + detect ──────────────────────────────────────────────
        artifact.raw_html = outcome.body  # transient; worker snapshots then clears
        page = parse_html(
            outcome.body,
            final_url=outcome.final_url or source.original,
            mode=CrawlMode.RAW,
            trailing_slash_policy=request.trailing_slash_policy,
        )
        self._apply_page(artifact, page)
        artifact.detection = detect_mod.detect(
            status=outcome.status,
            headers=outcome.headers,
            body=outcome.body,
            signals=artifact.signals,
        )

        matched = self._match_links(page.links, request)
        if matched:
            artifact.matched_links = matched
            artifact.found_in_raw = True

        # ── Render escalation (LNK-09) ──────────────────────────────────────
        should_render = (
            not artifact.found_in_raw
            and request.allow_render
            and self.config.render_enabled
            and not artifact.detection.captcha
            and not artifact.detection.cloudflare_challenge
            and self._looks_js_driven(outcome.body)
        )
        if should_render and self._browser is not None:
            await self._render_and_rematch(artifact, request, outcome)
        elif should_render:
            # No browser in this process → tell the HTTP pool to escalate (Arch §6).
            artifact.render_recommended = True

        return artifact

    # ── Internals ────────────────────────────────────────────────────────────
    def _apply_fetch(self, artifact: CrawlArtifact, outcome: FetchOutcome) -> None:
        artifact.fetch_error = outcome.error
        artifact.fetch_error_detail = outcome.error_detail
        artifact.http_status = outcome.status
        artifact.final_url = outcome.final_url
        artifact.redirect_chain = outcome.redirect_chain
        artifact.content_type = outcome.content_type
        artifact.content_length = outcome.body_bytes
        artifact.encoding = outcome.encoding
        artifact.response_headers = outcome.headers
        artifact.tls_valid = outcome.tls_valid
        artifact.crawl_duration_ms = outcome.duration_ms

    def _apply_page(self, artifact: CrawlArtifact, page) -> None:
        artifact.meta_robots = page.meta_robots
        artifact.canonical_url = page.canonical_url
        artifact.canonical_count = page.canonical_count
        artifact.base_href = page.base_href
        artifact.signals = page.signals
        artifact.all_links = page.links
        if page.canonical_url and artifact.final_url:
            resolved = normalize_url(page.canonical_url, base_url=artifact.final_url)
            artifact.canonical_resolved = resolved.normalized if resolved.valid else None

    def _match_links(self, links: list[ParsedLink], request: CrawlRequest) -> list[ParsedLink]:
        targets = {
            normalize_url(
                request.target_url, trailing_slash_policy=request.trailing_slash_policy
            ).normalized
        }
        if request.expected_target_url:
            exp = normalize_url(
                request.expected_target_url,
                trailing_slash_policy=request.trailing_slash_policy,
            )
            if exp.valid:
                targets.add(exp.normalized)
        targets.discard("")
        return [link for link in links if link.normalized_url in targets]

    def _looks_js_driven(self, body: str) -> bool:
        if not body:
            return True
        low = body.lower()
        if any(marker in low for marker in _JS_FRAMEWORK_MARKERS):
            return True
        script_bytes = sum(len(m) for m in re.findall(r"<script[\s\S]*?</script>", low))
        total = max(len(low), 1)
        text_only = re.sub(r"<[^>]+>", " ", low)
        text_ratio = len(text_only.strip()) / total
        script_ratio = script_bytes / total
        return (
            text_ratio < self.config.render_min_text_ratio
            or script_ratio > self.config.render_script_heavy_ratio
        )

    async def _render_and_rematch(
        self, artifact: CrawlArtifact, request: CrawlRequest, outcome: FetchOutcome
    ) -> None:
        from app.core.metrics import RENDER_ESCALATIONS

        RENDER_ESCALATIONS.inc()
        result = await self._browser.render(  # type: ignore[union-attr]
            outcome.final_url or request.source_url,
            timeout_ms=self.config.render_timeout_ms,
            wait_until=self.config.render_wait_until,
        )
        if not getattr(result, "ok", False):
            return
        artifact.rendered = True
        artifact.rendered_html = result.html
        rendered_page = parse_html(
            result.html,
            final_url=result.final_url or outcome.final_url or request.source_url,
            mode=CrawlMode.RENDERED,
            trailing_slash_policy=request.trailing_slash_policy,
        )
        matched = self._match_links(rendered_page.links, request)
        if matched:
            artifact.matched_links = matched
            artifact.found_in_rendered = True
            artifact.crawl_mode = CrawlMode.RENDERED
            artifact.all_links = rendered_page.links

    async def _evaluate_robots(
        self, url: str, user_agent: str, request: CrawlRequest
    ) -> RobotsResult:
        result = RobotsResult()
        norm = normalize_url(url)
        if not norm.valid:
            return result
        robots_url = f"https://{norm.host_ascii}/robots.txt"
        content = await self._fetch_robots(robots_url)
        if content is None:
            result.fetched = False
            return result
        result.fetched = True
        robots = RobotsTxt.parse(content)
        result.parse_error = robots.parse_error
        result.matched_user_agent = "Googlebot"
        result.source_allowed = robots.allowed(norm.original, "Googlebot")
        result.crawl_delay = robots.crawl_delay("Googlebot")
        result.sitemaps = robots.sitemaps
        # Target allowed (same host shortcut; cross-host evaluated best-effort).
        tnorm = normalize_url(request.target_url)
        if tnorm.valid and tnorm.host_ascii == norm.host_ascii:
            result.target_allowed = robots.allowed(tnorm.original, "Googlebot")
        return result

    async def _fetch_robots(self, robots_url: str) -> str | None:
        cache_key = f"robots:{robots_url}"
        if self._robots_cache is not None:
            cached = await self._robots_cache.get(cache_key)
            if cached is not None:
                return cached if cached != "\x00" else None
        try:
            resp = await self.client.get(
                robots_url, timeout=_ROBOTS_FETCH_TIMEOUT, follow_redirects=True
            )
            content = resp.text if resp.status_code == 200 else ""
        except Exception:  # noqa: BLE001 - robots failure → treat as allow-all (RBT-02)
            content = ""
        if self._robots_cache is not None:
            await self._robots_cache.set(
                cache_key, content or "\x00", self.config.robots_ttl
            )
        return content or None


async def crawl_one(request: CrawlRequest, config: CrawlConfig | None = None) -> CrawlArtifact:
    """Convenience one-shot crawl (used by the API single-recheck path)."""
    async with CrawlEngine(config or CrawlConfig.from_settings()) as engine:
        return await engine.crawl(request)
