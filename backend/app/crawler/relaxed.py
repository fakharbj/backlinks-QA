"""Link-type-aware RELAXED matching for GBP/GMB/citation placements (pure).

Owner rule: for link types whose name contains "GBP"/"GMB", the agreed deliverable
is often a *listing*, not the money URL. When the strict matcher finds no link to
the target, accept — in priority order:

1. ``gbp_map``          — a link to a Google Maps / GBP listing
                          (maps.google.*, google.com/maps, g.page, goo.gl/maps,
                          maps.app.goo.gl, *.business.site).
2. ``owned_directory``  — a link to one of OUR OWN directory domains
                          (settings.OWNED_DIRECTORY_DOMAINS) whose URL also
                          carries the business-name tokens, e.g.
                          citybizlocal.com/business/picture-perfect-glass/.

This module is deliberately framework-free (like ``integrations/serp.classify_serp_html``)
so it is unit-testable offline. It NEVER runs unless the request opted in
(``relaxed_match=True``) and the strict matcher already missed — so ordinary link
types are untouched and a real domain-scope match always wins.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from app.crawler.normalize import registrable_domain
from app.crawler.types import ParsedLink

# Hosts that ARE a Google Maps / GBP listing. Suffix-matched on the hostname.
_MAP_HOST_SUFFIXES = (
    "maps.google.com",
    "maps.app.goo.gl",
    "g.page",
    "business.site",
)
# google.<tld>/maps and goo.gl/maps are path-scoped (the bare hosts are not maps).
_MAP_PATH_HOSTS = ("google.", "goo.gl")

# Tokens too generic to identify a business on their own (kept short on purpose —
# a token must be distinctive, not merely present).
_STOP_TOKENS = frozenset({
    "the", "and", "for", "inc", "llc", "ltd", "co", "com", "www", "of", "a", "an",
    "service", "services", "company", "group", "solutions", "online", "official",
})


def _is_map_link(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if any(host == s or host.endswith("." + s) for s in _MAP_HOST_SUFFIXES):
        return True
    path = (parts.path or "").lower()
    if host.startswith("goo.gl") and path.startswith("/maps"):
        return True
    # google.com/maps, www.google.co.uk/maps/place/… — any google.* host + /maps.
    if ("google." in host) and path.startswith("/maps"):
        return True
    return False


def business_tokens(*sources: str | None) -> list[str]:
    """Distinctive lowercase word tokens from business-name sources (project
    business name / project name / target-domain label). Stoplist + min-length
    guarded so generic words can't fake a match."""
    out: list[str] = []
    seen: set[str] = set()
    for src in sources:
        if not src:
            continue
        for tok in re.split(r"[^a-z0-9]+", src.lower()):
            if len(tok) >= 3 and tok not in _STOP_TOKENS and tok not in seen:
                seen.add(tok)
                out.append(tok)
    return out


def _tokens_in_url(tokens: list[str], url: str) -> bool:
    """True when the URL's host+path carries the business identity: ALL distinctive
    tokens for 1-2-token names, else at least half (rounded up) — so long names
    tolerate a dropped word but a single generic hit never qualifies."""
    if not tokens:
        return False
    parts = urlsplit(url.lower())
    hay = f"{parts.hostname or ''}{parts.path or ''}"
    hits = sum(1 for t in tokens if t in hay)
    need = len(tokens) if len(tokens) <= 2 else (len(tokens) + 1) // 2
    return hits >= need


def find_relaxed_match(
    links: list[ParsedLink],
    *,
    tokens: list[str],
    owned_directories: list[str],
) -> tuple[ParsedLink, str] | None:
    """First acceptable alternate-target link, with the reason it matched
    (``gbp_map`` | ``owned_directory``). None = no relaxed match either."""
    owned = {d.strip().lower().lstrip(".") for d in owned_directories if d and d.strip()}

    # Priority 1 — a Google Maps / GBP listing link.
    for link in links:
        if _is_map_link(link.normalized_url):
            return link, "gbp_map"

    # Priority 2 — our own directory, verified against the business identity.
    # Without tokens we do NOT accept (a random listing on the same directory
    # must never validate this backlink).
    if owned and tokens:
        for link in links:
            dom = registrable_domain(urlsplit(link.normalized_url).hostname or "")
            if dom in owned and _tokens_in_url(tokens, link.normalized_url):
                return link, "owned_directory"
    return None
