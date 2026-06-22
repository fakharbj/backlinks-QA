"""HTML parsing & signal extraction (lxml).

Turns a raw/rendered HTML body into the structured signals the QA engine needs:
parsed link list (with region + hidden/comment/iframe detection), meta robots,
X-Robots-Tag (from headers), canonical, and page-quality metrics. Robust to
malformed markup (lxml's recovering parser).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

from lxml import etree, html as lxml_html

from app.crawler.normalize import normalize_for_match, normalize_url, registrable_domain
from app.crawler.types import CrawlMode, PageSignals, ParsedLink, RobotsDirectives

_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)
_HREF_IN_COMMENT_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_HIDDEN_STYLE_RE = re.compile(
    r"(display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?!\.)|"
    r"(?:width|height)\s*:\s*0(?:px)?\b|text-indent\s*:\s*-\d{4,}|"
    r"left\s*:\s*-\d{4,}px|clip\s*:\s*rect\(0)",
    re.IGNORECASE,
)
_HIDDEN_CLASS_HINTS = ("hidden", "hide", "visually-hidden", "sr-only", "screen-reader")
_SPONSORED_HINTS = ("sponsor", "advert", "ad-", "-ad", "ads", "promote", "promoted")
_UGC_HINTS = ("comment", "ugc", "disqus", "reply", "user-content", "review")
_REGION_TAGS = {
    "header": "header",
    "nav": "nav",
    "footer": "footer",
    "aside": "sidebar",
}
_SPAM_KEYWORDS = (
    "viagra", "cialis", "casino", "poker", "porn", "escort", "payday loan",
    "replica watch", "weight loss pill",
)


@dataclass(slots=True)
class ParsedPage:
    links: list[ParsedLink] = field(default_factory=list)
    meta_robots: RobotsDirectives = field(default_factory=RobotsDirectives)
    canonical_url: str | None = None
    canonical_count: int = 0
    base_href: str | None = None
    signals: PageSignals = field(default_factory=PageSignals)


# ── Robots directive parsing (shared by meta + header) ──────────────────────────
def parse_robots_directives(value: str) -> RobotsDirectives:
    """Parse a meta-robots / X-Robots-Tag value, incl. UA-prefixed tokens."""
    directives = RobotsDirectives(raw=value)
    if not value:
        return directives
    ua_specific: dict[str, str] = {}
    seen_index: list[bool] = []
    seen_follow: list[bool] = []

    # A value may be "googlebot: noindex, nofollow" or just "noindex".
    segment = value
    if ":" in value.split(",", 1)[0]:
        ua, _, rest = value.partition(":")
        ua_specific[ua.strip().lower()] = rest.strip().lower()
        directives.ua_specific = ua_specific
        segment = rest

    for token in (t.strip().lower() for t in segment.split(",")):
        if not token:
            continue
        if token == "none":
            directives.none = True
            directives.index = False
            directives.follow = False
        elif token == "noindex":
            directives.index = False
            seen_index.append(False)
        elif token == "index":
            seen_index.append(True)
        elif token == "nofollow":
            directives.follow = False
            seen_follow.append(False)
        elif token == "follow":
            seen_follow.append(True)
        elif token == "noarchive":
            directives.noarchive = True
        elif token == "nosnippet":
            directives.nosnippet = True
        elif token.startswith("unavailable_after"):
            directives.unavailable_after = _parse_unavailable_after(token)

    # Conflicting directives (both index & noindex present) → flag (MR-05/XR-05).
    if (True in seen_index and False in seen_index) or (
        True in seen_follow and False in seen_follow
    ):
        directives.conflicting = True
    return directives


def _parse_unavailable_after(token: str) -> "object | None":
    from datetime import datetime

    raw = token.split(":", 1)[-1].strip()
    for fmt in ("%d-%b-%Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def parse_x_robots_header(header_values: list[str]) -> RobotsDirectives:
    """Combine one or more X-Robots-Tag headers (most-restrictive wins)."""
    combined = RobotsDirectives(raw="; ".join(header_values))
    for value in header_values:
        d = parse_robots_directives(value)
        combined.index = combined.index and d.index
        combined.follow = combined.follow and d.follow
        combined.none = combined.none or d.none
        combined.noarchive = combined.noarchive or d.noarchive
        combined.nosnippet = combined.nosnippet or d.nosnippet
        combined.conflicting = combined.conflicting or d.conflicting
        combined.ua_specific.update(d.ua_specific)
        if d.unavailable_after:
            combined.unavailable_after = d.unavailable_after
    return combined


# ── Element helpers ─────────────────────────────────────────────────────────────
def _ancestor_region(el: object) -> tuple[str, bool, bool, bool]:
    """Walk ancestors → ``(region, in_iframe, sponsored_block, ugc_block)``."""
    region = "body"
    in_iframe = sponsored = ugc = False
    node = el.getparent() if hasattr(el, "getparent") else None
    depth = 0
    while node is not None and depth < 40:
        tag = str(getattr(node, "tag", "")).lower()
        if tag == "iframe":
            in_iframe = True
        if region == "body" and tag in _REGION_TAGS:
            region = _REGION_TAGS[tag]
        ident = " ".join(
            filter(None, [node.get("class", ""), node.get("id", ""), node.get("role", "")])
        ).lower()
        if region == "body" and ("sidebar" in ident):
            region = "sidebar"
        if any(h in ident for h in _SPONSORED_HINTS):
            sponsored = True
        if any(h in ident for h in _UGC_HINTS):
            ugc = True
        node = node.getparent()
        depth += 1
    return region, in_iframe, sponsored, ugc


def _is_css_hidden(el: object) -> bool:
    style = (el.get("style") or "").lower()
    if style and _HIDDEN_STYLE_RE.search(style):
        return True
    if el.get("hidden") is not None:
        return True
    if el.get("aria-hidden") == "true":
        return True
    classes = (el.get("class") or "").lower()
    return any(h in classes.split() for h in _HIDDEN_CLASS_HINTS)


def _in_noscript(el: object) -> bool:
    node = el.getparent()
    depth = 0
    while node is not None and depth < 40:
        if str(getattr(node, "tag", "")).lower() == "noscript":
            return True
        node = node.getparent()
        depth += 1
    return False


def _context_text(el: object, width: int = 160) -> str:
    parent = el.getparent()
    if parent is None:
        return (el.text or "").strip()[:width]
    try:
        text = " ".join(parent.itertext())
    except Exception:
        text = parent.text or ""
    return re.sub(r"\s+", " ", text).strip()[:width]


# ── Main parse ──────────────────────────────────────────────────────────────────
def parse_html(
    body: str,
    *,
    final_url: str,
    mode: CrawlMode = CrawlMode.RAW,
    trailing_slash_policy: str = "lenient",
) -> ParsedPage:
    page = ParsedPage()
    if not body:
        return page

    try:
        tree = lxml_html.fromstring(body)
    except (etree.ParserError, ValueError):
        return page

    # <base href> affects relative resolution (rule 8).
    base_href = final_url
    base_el = tree.find(".//base[@href]")
    if base_el is not None and base_el.get("href"):
        page.base_href = base_el.get("href")
        resolved_base = normalize_url(base_el.get("href"), base_url=final_url)
        if resolved_base.valid:
            base_href = resolved_base.original if not resolved_base.normalized else base_el.get("href")
    base_for_links = page.base_href or final_url

    _extract_meta(tree, page)
    _extract_dates(tree, page)  # before _extract_signals strips <script> (JSON-LD)
    _extract_links(tree, page, base_for_links, final_url, mode, trailing_slash_policy)
    _extract_signals(tree, body, page)

    # Comment-embedded links (LNK-11): scanned from raw markup, flagged hidden.
    _extract_comment_links(tree, page, base_for_links, trailing_slash_policy)
    return page


def _extract_meta(tree: object, page: ParsedPage) -> None:
    robots_values: list[str] = []
    for meta in tree.iter("meta"):
        name = (meta.get("name") or "").lower()
        if name in ("robots", "googlebot", "googlebot-news"):
            content = meta.get("content") or ""
            robots_values.append(f"{name}: {content}" if name != "robots" else content)
    if robots_values:
        page.meta_robots = parse_robots_directives(", ".join(robots_values))

    canonicals = [
        link.get("href")
        for link in tree.iter("link")
        if "canonical" in (link.get("rel") or "").lower() and link.get("href")
    ]
    page.canonical_count = len(canonicals)
    if canonicals:
        page.canonical_url = canonicals[0]


# ── Published-date extraction ───────────────────────────────────────────────────
# Meta property/name keys that commonly carry the publish date, in priority order.
_PUBLISHED_META_KEYS = (
    "article:published_time", "datepublished", "date", "pubdate", "publishdate",
    "publish-date", "publication_date", "dc.date", "dc.date.issued", "sailthru.date",
    "parsely-pub-date", "og:published_time", "rnews:datepublished",
)
_MODIFIED_META_KEYS = ("article:modified_time", "datemodified", "og:updated_time", "lastmod")


def _extract_dates(tree: object, page: ParsedPage) -> None:
    """Find the page's posted/published date from JSON-LD, meta tags, or <time>.

    Tries the most reliable sources first and stops at the first hit. Leaves the
    fields ``None`` when nothing trustworthy is present (the UI then shows a plain
    "not detected" line rather than guessing).
    """
    s = page.signals
    published = modified = None
    source: str | None = None

    # 1) JSON-LD (schema.org Article/BlogPosting/NewsArticle) — most reliable.
    for script in tree.iter("script"):
        if "ld+json" not in (script.get("type") or "").lower():
            continue
        raw = (script.text or "") or "".join(getattr(script, "itertext", lambda: [])())
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        for node in _iter_jsonld_nodes(data):
            if published is None and node.get("datePublished"):
                published, source = node.get("datePublished"), "json-ld"
            if published is None and node.get("dateCreated"):
                published, source = node.get("dateCreated"), "json-ld"
            if modified is None and node.get("dateModified"):
                modified = node.get("dateModified")
        if published:
            break

    # 2) Meta tags (Open Graph, Dublin Core, itemprop, publisher-specific).
    if published is None:
        for meta in tree.iter("meta"):
            key = (
                meta.get("property") or meta.get("name") or meta.get("itemprop") or ""
            ).lower()
            content = (meta.get("content") or "").strip()
            if not content:
                continue
            if published is None and key in _PUBLISHED_META_KEYS:
                published, source = content, "meta"
            if modified is None and key in _MODIFIED_META_KEYS:
                modified = content

    # 3) A <time> element explicitly marked as the publish date.
    if published is None:
        for tel in tree.iter("time"):
            dt = (tel.get("datetime") or "").strip()
            if not dt:
                continue
            itemprop = (tel.get("itemprop") or "").lower()
            hint = " ".join(
                filter(None, [tel.get("class", ""), tel.get("id", ""), itemprop])
            ).lower()
            if (
                tel.get("pubdate") is not None
                or "datepublished" in itemprop
                or any(h in hint for h in ("publish", "posted", "entry-date", "post-date"))
            ):
                published, source = dt, "time"
                break

    s.published_date = _clean_date(published)
    s.modified_date = _clean_date(modified)
    s.date_source = source if s.published_date else None


def _iter_jsonld_nodes(data: object):
    """Yield every dict in a JSON-LD blob (handles arrays and @graph nesting)."""
    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from _iter_jsonld_nodes(value)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_jsonld_nodes(item)


_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y",
    "%d %B %Y", "%B %d, %Y", "%d %b %Y", "%b %d, %Y", "%B %d %Y",
)


def _clean_date(value: object) -> str | None:
    """Normalise a found date to YYYY-MM-DD; fall back to the raw text if odd."""
    if not value:
        return None
    raw = str(value).strip()[:60]
    if not raw:
        return None
    iso = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso).date().isoformat()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return raw  # show whatever the page provided rather than dropping it


def _extract_links(
    tree: object,
    page: ParsedPage,
    base_href: str,
    final_url: str,
    mode: CrawlMode,
    trailing_slash_policy: str,
) -> None:
    source_domain = registrable_domain(normalize_url(final_url).host_ascii or final_url)
    internal = external = 0
    for a in tree.iter("a"):
        href = a.get("href")
        if not href:
            continue
        href = href.strip()
        if href.lower().startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        norm = normalize_url(href, base_url=base_href, trailing_slash_policy=trailing_slash_policy)
        if not norm.valid:
            continue

        region, in_iframe, sponsored, ugc = _ancestor_region(a)
        rel = [r for r in re.split(r"\s+", (a.get("rel") or "").lower()) if r]
        anchor = re.sub(r"\s+", " ", " ".join(a.itertext())).strip()
        img = a.find(".//img")
        image_alt = img.get("alt") if img is not None else None

        link = ParsedLink(
            href=href,
            resolved_url=norm.original if norm.normalized else href,
            normalized_url=norm.normalized,
            anchor_text=anchor,
            image_alt=image_alt,
            rel=rel,
            region=region,
            in_comment=False,
            in_iframe=in_iframe,
            in_noscript=_in_noscript(a),
            css_hidden=_is_css_hidden(a),
            sponsored_block=sponsored,
            ugc_block=ugc,
            context_text=_context_text(a),
            source_mode=mode,
        )
        page.links.append(link)
        if norm.registrable_domain == source_domain:
            internal += 1
        else:
            external += 1

    page.signals.internal_link_count = internal
    page.signals.external_link_count = external
    page.signals.outbound_link_count = external


def _extract_comment_links(
    tree: object, page: ParsedPage, base_href: str, trailing_slash_policy: str
) -> None:
    for comment in tree.iter(etree.Comment):
        text = comment.text or ""
        for href in _HREF_IN_COMMENT_RE.findall(text):
            norm = normalize_url(
                href, base_url=base_href, trailing_slash_policy=trailing_slash_policy
            )
            if not norm.valid:
                continue
            page.links.append(
                ParsedLink(
                    href=href,
                    resolved_url=href,
                    normalized_url=norm.normalized,
                    in_comment=True,
                    css_hidden=True,
                    context_text="(inside HTML comment)",
                )
            )


def _extract_signals(tree: object, body: str, page: ParsedPage) -> None:
    s = page.signals
    title_el = tree.find(".//title")
    s.title = (title_el.text or "").strip() if title_el is not None else None

    for meta in tree.iter("meta"):
        if (meta.get("name") or "").lower() == "description":
            s.meta_description = (meta.get("content") or "").strip()
            break

    h1 = tree.find(".//h1")
    if h1 is not None:
        s.h1 = re.sub(r"\s+", " ", " ".join(h1.itertext())).strip()

    html_el = tree if str(getattr(tree, "tag", "")) == "html" else tree.find(".//html")
    if html_el is not None and html_el.get("lang"):
        s.language = html_el.get("lang")

    # Visible-text word count: drop script/style/noscript subtrees. Collect first —
    # mutating the tree mid-iteration is unsafe in lxml.
    for bad in list(tree.iter("script", "style", "noscript")):
        parent = bad.getparent()
        if parent is not None:
            parent.remove(bad)
    text = " ".join(tree.itertext())
    s.word_count = len(_WORD_RE.findall(text))
    s.page_bytes = len(body.encode("utf-8", errors="ignore"))

    low = text.lower()
    s.spam_keyword_hits = [kw for kw in _SPAM_KEYWORDS if kw in low]
