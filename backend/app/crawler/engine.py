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
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol
from urllib.parse import urlsplit

import httpx

from app.crawler import detect as detect_mod
from app.crawler.fetch import FetchOutcome, build_client, fetch_raw
from app.crawler.normalize import normalize_url, registrable_domain
from app.crawler.parse import extract_markdown_links, parse_html, parse_x_robots_header
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
    "id=\"notion-app\"", "id=\"__next\"", "id=\"__nuxt\"", "id=\"___gatsby\"",
)
_ROBOTS_FETCH_TIMEOUT = 8.0

# When an https-first attempt fails at the transport level we retry the original
# http:// URL (the secure endpoint genuinely isn't reachable). A real HTTP answer
# like 403/404 is kept as-is — it's the site's true response.
_HTTPS_FALLBACK_ERRORS = (
    FetchError.DNS,
    FetchError.SSL,
    FetchError.CONNECTION,
    FetchError.TIMEOUT,
)

# Signals that a page is blocked / behind a bot challenge and is worth retrying
# through the proxy (PROXY_MODE=escalate).
_BLOCK_STATUSES = {403, 429, 503, 520, 521, 522, 523, 524, 525, 526, 530}
# STRONG, unambiguous interstitial fingerprints. We deliberately exclude weak words
# like "captcha"/"recaptcha"/"access denied" because normal content pages reference
# them in scripts (e.g. Crunchbase loads reCAPTCHA for its forms) — matching those
# caused false "blocked" verdicts and needless proxy escalation.
_CHALLENGE_MARKERS = (
    "just a moment", "cf-browser-verification", "/cdn-cgi/challenge-platform",
    "attention required! | cloudflare", "checking your browser before",
    "ddos protection by cloudflare", "please enable cookies and reload",
    "verifying you are human",
    # Cloudflare managed-challenge fingerprints (served with HTTP 200 to bots —
    # e.g. notion.site): the unblocker proxy can clear these.
    "__cf_chl", "cf_chl_opt", "enable javascript and cookies to continue",
    # AWS WAF browser challenge (served with HTTP 202 by site builders like
    # site123): browsers solve it silently; a naive crawler sees an empty shell.
    "awswafcookiedomainlist", "gokuprops", "aws-waf-token", "challenge.compact.js",
)
# Challenge interstitials are small; a full content page that merely mentions a
# captcha script is large, so a size guard avoids false positives.
_CHALLENGE_MAX_BYTES = 60_000


def _looks_blocked(outcome: "FetchOutcome") -> bool:
    """A block *status*, or a small page carrying a strong challenge fingerprint."""
    if outcome.status in _BLOCK_STATUSES:
        return True
    body = outcome.body or ""
    if body and len(body) < _CHALLENGE_MAX_BYTES:
        low = body.lower()
        return any(marker in low for marker in _CHALLENGE_MARKERS)
    return False


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
    https_first: bool = True
    # Proxy egress (IPRoyal Web Unblocker). proxy_mode: "off" | "escalate" | "always".
    proxy_mode: str = "off"
    proxy_egress_url: str | None = None
    proxy_verify: bool = False
    proxy_timeout: float = 90.0
    proxy_headers: dict = field(default_factory=dict)
    proxy_render_on_js_missing: bool = True
    render_enabled: bool = True
    render_timeout_ms: int = 20_000
    render_wait_until: str = "networkidle"
    render_min_text_ratio: float = 0.10
    render_script_heavy_ratio: float = 0.55
    proxy: str | None = None

    @classmethod
    def from_settings(cls) -> "CrawlConfig":
        from app.core.config import settings
        from app.integrations import proxy

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
            https_first=settings.CRAWL_HTTPS_FIRST,
            proxy_mode=proxy.mode(),
            proxy_egress_url=proxy.proxy_url(),
            proxy_verify=settings.PROXY_VERIFY_TLS,
            proxy_timeout=settings.PROXY_TIMEOUT,
            proxy_headers=dict(settings.PROXY_HEADERS),
            proxy_render_on_js_missing=settings.PROXY_RENDER_ON_JS_MISSING,
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
        self._proxy_client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "CrawlEngine":
        self._client = build_client(
            user_agent=self.config.user_agent,
            connect_timeout=self.config.connect_timeout,
            read_timeout=self.config.read_timeout,
            total_timeout=self.config.total_timeout,
            proxy=self.config.proxy,
        )
        # A second client routed through the IPRoyal Web Unblocker, used when a
        # page is blocked (escalate) or for every request (always). The unblocker
        # MITMs TLS, so verification is off; http/2 is disabled for proxy safety.
        if self.config.proxy_egress_url and self.config.proxy_mode in ("escalate", "always"):
            self._proxy_client = build_client(
                user_agent=self.config.user_agent,
                connect_timeout=self.config.connect_timeout,
                read_timeout=self.config.proxy_timeout,
                total_timeout=self.config.proxy_timeout,
                proxy=self.config.proxy_egress_url,
                verify=self.config.proxy_verify,
                http2=False,
            )
            if self.config.proxy_headers:
                self._proxy_client.headers.update(self.config.proxy_headers)
        return self

    async def __aexit__(self, *exc) -> None:
        for client in (self._client, self._proxy_client):
            if client is not None:
                await client.aclose()
        self._client = self._proxy_client = None

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

        # ── Raw fetch (direct, then escalate to proxy if blocked) ────────────
        retry_ua = (
            self.config.googlebot_ua
            if (self.config.block_retry and not request.use_googlebot_ua)
            else None
        )

        async def _fetch_via(client: httpx.AsyncClient, *, via_proxy: bool) -> FetchOutcome:
            # The unblocker manages anti-bot itself, so skip the alt-UA retry there.
            ua_retry = None if via_proxy else retry_ua

            async def _one(target: str) -> FetchOutcome:
                return await fetch_raw(
                    client, target, request,
                    max_redirects=self.config.max_redirects,
                    max_bytes=self.config.max_bytes,
                    retry_user_agent=ua_retry,
                )

            # HTTPS-first: for any http:// source, request the secure URL up front
            # (browser-like, skips the http→https hop, fewer bot challenges). Fall
            # back to http only if https is unreachable at the transport level.
            if self.config.https_first and source.original.lower().startswith("http://"):
                https_target = "https://" + source.original[len("http://"):]
                out = await _one(https_target)
                if out.error in _HTTPS_FALLBACK_ERRORS:
                    out = await _one(source.original)
                return out
            return await _one(source.original)

        if self.config.proxy_mode == "always" and self._proxy_client is not None:
            outcome = await _fetch_via(self._proxy_client, via_proxy=True)
            artifact.egress = "proxy"
        else:
            outcome = await _fetch_via(self.client, via_proxy=False)
            artifact.egress = "direct"
            # Escalate a blocked page (403/429/5xx or a Cloudflare/CAPTCHA body)
            # through the proxy, and keep the proxied result if it cleared the block.
            if (
                self.config.proxy_mode == "escalate"
                and self._proxy_client is not None
                and _looks_blocked(outcome)
            ):
                proxied = await _fetch_via(self._proxy_client, via_proxy=True)
                # Only adopt the proxied result if it genuinely succeeded and isn't
                # itself blocked. A proxy transport error (SSL/timeout) must NEVER
                # replace a good direct result — keep the honest direct outcome.
                if proxied.error is FetchError.NONE and not _looks_blocked(proxied):
                    outcome = proxied
                    artifact.egress = "proxy"

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
        if not matched:
            # Markdown pads (HedgeDoc/CodiMD, wikis) serve raw markdown that the
            # browser renders into real anchors — match "[anchor](target)" text
            # directly so these pages don't false-fail as "link missing".
            matched = self._match_markdown(outcome.body, request, outcome.final_url or source.original)
            if matched:
                page.links.extend(matched)
        if matched:
            artifact.matched_links = matched
            artifact.found_in_raw = True

        # ── Proxy-render escalation ─────────────────────────────────────────
        # The link is absent from raw HTML and the page looks JS-driven (e.g. an
        # Angular/React SPA that injects the link client-side). Re-fetch through
        # the IPRoyal proxy — which can render JavaScript — and re-parse/re-match.
        if (
            not artifact.found_in_raw
            and request.allow_render
            and self.config.proxy_render_on_js_missing
            and self._proxy_client is not None
            and artifact.egress != "proxy"
            # Accuracy-max lab mode bypasses the captcha guard: the unblocker
            # proxy is built to clear challenges, so let it try.
            and (request.force_render_on_missing or not artifact.detection.captcha)
            and (self._looks_js_driven(outcome.body) or not page.links or request.force_render_on_missing)
        ):
            proxied = await _fetch_via(self._proxy_client, via_proxy=True)
            if proxied.error is FetchError.NONE and proxied.status and proxied.status < 400:
                outcome = proxied
                artifact.egress = "proxy"
                self._apply_fetch(artifact, outcome)
                if artifact.is_html:
                    artifact.raw_html = outcome.body
                    page = parse_html(
                        outcome.body,
                        final_url=outcome.final_url or source.original,
                        mode=CrawlMode.RAW,
                        trailing_slash_policy=request.trailing_slash_policy,
                    )
                    self._apply_page(artifact, page)
                    artifact.detection = detect_mod.detect(
                        status=outcome.status, headers=outcome.headers,
                        body=outcome.body, signals=artifact.signals,
                    )
                    matched = self._match_links(page.links, request)
                    if not matched:
                        matched = self._match_markdown(
                            outcome.body, request, outcome.final_url or source.original
                        )
                        if matched:
                            page.links.extend(matched)
                    if matched:
                        artifact.matched_links = matched
                        artifact.found_in_raw = True

        # ── Render escalation (LNK-09) ──────────────────────────────────────
        # A bot-block status (401/403/429/503) ALWAYS gets a browser attempt:
        # many sites (Medium, WAFs) reject automated requests — including with a
        # Cloudflare/JS challenge page — but serve a real browser fine. The
        # browser verdict is the accurate one there, so the challenge/captcha
        # exclusions (which exist to avoid rendering unwinnable challenges on
        # otherwise-200 pages) do not apply to blocked statuses: worst case the
        # browser is challenged too and nothing changes.
        blocked_status = outcome.status in (401, 403, 429, 503)
        should_render = (
            not artifact.found_in_raw
            and request.allow_render
            and self.config.render_enabled
            and (
                blocked_status
                or request.force_render_on_missing
                or (
                    not artifact.detection.captcha
                    and not artifact.detection.cloudflare_challenge
                )
            )
            # An HTML page that parses to ZERO links is an app shell (Notion,
            # SPAs) — real pages always carry some links. Render it. In lab
            # accuracy-max mode, render whenever the link is still missing
            # (Medium/Substack inject article-body links client-side, so the
            # server/proxy HTML carries only nav/footer links).
            and (
                self._looks_js_driven(outcome.body)
                or not page.links
                or blocked_status
                or request.force_render_on_missing
            )
        )
        if should_render and self._browser is not None:
            await self._render_and_rematch(artifact, request, outcome)
        elif should_render:
            # No browser in this process → tell the HTTP pool to escalate (Arch §6).
            artifact.render_recommended = True

        # ── Relaxed fallback (GBP/GMB/citation link types ONLY) ─────────────
        # Runs strictly LAST: only when every strict matcher (raw, markdown,
        # rendered) missed AND the worker opted this link type in. A Google
        # Maps/GBP listing link — or an owned-directory link carrying the
        # business tokens — counts as present, stamped with relaxed_reason so
        # LNK-18 discloses HOW it matched (reports never pretend it was the
        # exact agreed URL).
        if not artifact.matched_links and request.relaxed_match and artifact.all_links:
            from app.crawler.relaxed import find_relaxed_match

            hit = find_relaxed_match(
                artifact.all_links,
                tokens=request.business_tokens,
                owned_directories=request.owned_directory_domains,
            )
            if hit is not None:
                link, reason = hit
                artifact.matched_links = [link]
                artifact.relaxed_reason = reason

        # ── "Couldn't confirm" signal ───────────────────────────────────────
        # The link is STILL absent. Distinguish two very different cases:
        #   (a) we FULLY rendered the real page (headless browser returned a 2xx
        #       DOM) — the JavaScript content HAS been read, so an absent link is
        #       a genuine "not found", not uncertainty. Do NOT flag it.
        #   (b) we could NOT read the real content — the browser was blocked
        #       (403/challenge) or never ran, and all we have is a JS shell / a
        #       proxy fetch of a JS-driven page. THEN it's "couldn't confirm" →
        #       NEEDS_MANUAL_REVIEW, never a confident FAIL.
        rendered_ok = artifact.rendered and 200 <= (artifact.browser_http_status or 0) < 300
        if (
            not artifact.matched_links
            and artifact.is_html
            and artifact.fetch_error is FetchError.NONE
            and not rendered_ok
            and (self._looks_js_driven(outcome.body) or artifact.egress == "proxy")
        ):
            artifact.js_render_suspected = True

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

    def _match_markdown(
        self, body: str | None, request: CrawlRequest, final_url: str
    ) -> list[ParsedLink]:
        """Fallback matcher for pages that serve markdown instead of HTML."""
        if not body:
            return []
        md_links = extract_markdown_links(
            body, final_url=final_url, trailing_slash_policy=request.trailing_slash_policy
        )
        return self._match_links(md_links, request) if md_links else []

    def _match_links(self, links: list[ParsedLink], request: CrawlRequest) -> list[ParsedLink]:
        # Domain-scope matching: the agreed target is the project's main domain, so
        # a link to ANY page on that registrable domain counts as the backlink.
        if request.domain_match():
            target_dom = normalize_url(
                request.expected_target_url or request.target_url,
                trailing_slash_policy=request.trailing_slash_policy,
            ).registrable_domain
            if target_dom:
                return [
                    link
                    for link in links
                    if registrable_domain(urlsplit(link.normalized_url).hostname or "") == target_dom
                    or (
                        link.unwrapped_url is not None
                        and registrable_domain(urlsplit(link.unwrapped_url).hostname or "")
                        == target_dom
                    )
                ]

        # Exact-URL matching (default): only the agreed target URL(s) count.
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
        return [
            link
            for link in links
            if link.normalized_url in targets
            or (link.unwrapped_url is not None and link.unwrapped_url in targets)
        ]

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
            # Wait for the thing QA is actually looking for: any link to the
            # target's domain — hydration-proof and faster than generic idle.
            wait_selector=self._target_selector(request),
        )
        if not getattr(result, "ok", False):
            return
        artifact.rendered = True
        artifact.browser_http_status = getattr(result, "status", None)
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
        elif rendered_page.signals.doc_viewer and not artifact.signals.doc_viewer:
            # The RENDERED DOM revealed a PDF/document viewer the raw HTML didn't
            # (JS-built shells). Propagate so LNK-01 says "verify the document"
            # instead of a confident LINK_MISSING.
            artifact.signals.doc_viewer = True
            artifact.signals.doc_viewer_signature = rendered_page.signals.doc_viewer_signature

    @staticmethod
    def _target_selector(request: CrawlRequest) -> str | None:
        """CSS selector matching any anchor to the target's registrable domain."""
        norm = normalize_url(request.expected_target_url or request.target_url)
        dom = norm.registrable_domain if norm.valid else None
        if not dom or '"' in dom:
            return None
        return f'a[href*="{dom}"]'

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
