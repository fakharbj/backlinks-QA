"""URL normalization & canonicalization (PRD §8.4).

A single, well-tested normalizer used on ingest, comparison, and crawl. It returns
both a *normalized* form (for matching/indexing/dedup) and preserves the original
(for crawling/auditing), plus the decomposed components QA needs to flag scheme
downgrades and www discrepancies separately.

Design choices that make matching correct:
  * Scheme is normalised to ``https`` in the match form so ``http``↔``https`` dedup
    as "same resource" (rule 2); the real scheme is kept for downgrade detection.
  * Leading ``www.`` is stripped for matching (rule 4) but ``had_www`` is recorded.
  * IDN hosts are canonicalised to punycode/ASCII so unicode and ``xn--`` forms
    compare equal (rule 3).
  * Tracking params are dropped and the remainder sorted (rule 6); the fragment is
    dropped (rule 7) unless it is an SPA ``#!`` hashbang and the flag is set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

import idna
import tldextract

# A self-contained extractor (no network calls for the public-suffix list refresh).
_extract = tldextract.TLDExtract(suffix_list_urls=())

# Tracking parameters removed for *comparison* (preserved in the original).
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_PARAMS = frozenset(
    {
        "gclid", "fbclid", "mc_eid", "mc_cid", "_ga", "_gl", "mkt_tok", "igshid",
        "msclkid", "yclid", "dclid", "gclsrc", "wbraid", "gbraid", "vero_id",
        "oly_anon_id", "oly_enc_id", "ref", "ref_src", "spm", "scm", "_hsenc",
        "_hsmi", "hsa_cam", "hsa_grp", "hsa_ad",
    }
)

_DEFAULT_PORTS = {"http": 80, "https": 443, "ftp": 21}
_MULTI_SLASH = re.compile(r"/{2,}")
# Characters left unescaped in a normalised path (RFC 3986 unreserved + sub-set).
_PATH_SAFE = "/-._~!$&'()*+,;=:@"
_QUERY_SAFE = "-._~!$'()*+,;=:@/?"


def registrable_domain(host: str) -> str:
    """Return the registrable ("eTLD+1") domain, e.g. ``a.b.example.co.uk`` → ``example.co.uk``."""
    host = host.strip().lower().rstrip(".")
    ext = _extract(host)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}"
    return host  # IPs / intranet / unknown TLDs fall back to the bare host


def _canonical_host(host: str) -> tuple[str, str]:
    """Return ``(ascii_host, unicode_host)`` with IDN normalisation applied."""
    host = host.strip().lower().rstrip(".")
    if not host:
        return "", ""
    try:
        ascii_host = idna.encode(host, uts46=True).decode("ascii")
    except idna.IDNAError:
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except Exception:
            ascii_host = host
    try:
        unicode_host = idna.decode(ascii_host)
    except Exception:
        unicode_host = host
    return ascii_host, unicode_host


def _remove_dot_segments(path: str) -> str:
    """RFC 3986 §5.2.4 dot-segment resolution."""
    out: list[str] = []
    for seg in path.split("/"):
        if seg == ".":
            continue
        if seg == "..":
            if out and out[-1] != "":
                out.pop()
            continue
        out.append(seg)
    resolved = "/".join(out)
    if path.startswith("/") and not resolved.startswith("/"):
        resolved = "/" + resolved
    return resolved or "/"


def _normalize_path(path: str, *, trailing_slash_policy: str) -> str:
    if not path:
        return "/"
    # Decode then re-encode so equivalent encodings compare equal (rule 1).
    path = quote(unquote(path), safe=_PATH_SAFE)
    path = _MULTI_SLASH.sub("/", path)
    path = _remove_dot_segments(path)
    if trailing_slash_policy == "lenient" and len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    return path


def _clean_query(query: str) -> tuple[str, list[tuple[str, str]]]:
    """Drop tracking params, sort the rest. Returns ``(encoded, pairs)``."""
    if not query:
        return "", []
    pairs = parse_qsl(query, keep_blank_values=True)
    kept = [
        (k, v)
        for k, v in pairs
        if not (k.lower() in _TRACKING_PARAMS or k.lower().startswith(_TRACKING_PREFIXES))
    ]
    kept.sort()
    encoded = "&".join(
        f"{quote(k, safe=_QUERY_SAFE)}={quote(v, safe=_QUERY_SAFE)}" if v != "" else quote(k, safe=_QUERY_SAFE)
        for k, v in kept
    )
    return encoded, kept


@dataclass(slots=True)
class NormalizedUrl:
    original: str
    valid: bool
    normalized: str = ""                 # canonical match/index form
    scheme: str = ""                     # original scheme, lowercased
    host_ascii: str = ""                 # punycode host incl. any www
    host_unicode: str = ""
    registrable_domain: str = ""
    subdomain: str = ""
    port: int | None = None
    path: str = "/"
    query_pairs: list[tuple[str, str]] = field(default_factory=list)
    fragment: str = ""
    had_www: bool = False
    is_https: bool = False
    error: str | None = None

    @property
    def host_no_www(self) -> str:
        return self.host_ascii[4:] if self.host_ascii.startswith("www.") else self.host_ascii


def normalize_url(
    raw: str,
    *,
    base_url: str | None = None,
    trailing_slash_policy: str = "lenient",
    keep_hashbang: bool = False,
) -> NormalizedUrl:
    """Normalise ``raw`` (optionally resolved against ``base_url``) into a ``NormalizedUrl``."""
    if raw is None:
        return NormalizedUrl(original="", valid=False, error="empty")
    original = raw.strip()
    if not original:
        return NormalizedUrl(original=original, valid=False, error="empty")

    # Rule 8: resolve relative URLs against the (post-redirect) base.
    candidate = original
    if base_url:
        from urllib.parse import urljoin

        candidate = urljoin(base_url, original)

    try:
        parts = urlsplit(candidate)
    except ValueError as exc:
        return NormalizedUrl(original=original, valid=False, error=f"parse: {exc}")

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        # Non-web schemes (mailto:, tel:, javascript:) are not crawlable links.
        return NormalizedUrl(
            original=original, valid=False, scheme=scheme, error="unsupported_scheme"
        )

    host_ascii, host_unicode = _canonical_host(parts.hostname or "")
    if not host_ascii:
        return NormalizedUrl(original=original, valid=False, scheme=scheme, error="no_host")

    port = parts.port
    if port is not None and _DEFAULT_PORTS.get(scheme) == port:
        port = None  # rule 3: strip default ports

    had_www = host_ascii.startswith("www.")
    host_no_www = host_ascii[4:] if had_www else host_ascii

    path = _normalize_path(parts.path, trailing_slash_policy=trailing_slash_policy)
    query_encoded, query_pairs = _clean_query(parts.query)

    fragment = ""
    if keep_hashbang and parts.fragment.startswith("!"):
        fragment = parts.fragment  # rule 7 exception: SPA hashbang

    # Canonical match form: scheme pinned to https, www stripped, no fragment.
    authority = host_no_www if port is None else f"{host_no_www}:{port}"
    normalized = urlunsplit(("https", authority, path, query_encoded, fragment))

    ext = _extract(host_ascii)
    subdomain = ext.subdomain
    reg = f"{ext.domain}.{ext.suffix}" if ext.domain and ext.suffix else host_no_www

    return NormalizedUrl(
        original=original,
        valid=True,
        normalized=normalized,
        scheme=scheme,
        host_ascii=host_ascii,
        host_unicode=host_unicode,
        registrable_domain=reg,
        subdomain=subdomain,
        port=port,
        path=path,
        query_pairs=query_pairs,
        fragment=fragment,
        had_www=had_www,
        is_https=(scheme == "https"),
    )


@lru_cache(maxsize=4096)
def normalize_for_match(raw: str, trailing_slash_policy: str = "lenient") -> str:
    """Cheap cached helper returning just the canonical match string (or "")."""
    return normalize_url(raw, trailing_slash_policy=trailing_slash_policy).normalized


def urls_match(
    a: str,
    b: str,
    *,
    trailing_slash_policy: str = "lenient",
) -> bool:
    """True when two URLs are the same resource under the active policy (rule)."""
    na = normalize_url(a, trailing_slash_policy=trailing_slash_policy)
    nb = normalize_url(b, trailing_slash_policy=trailing_slash_policy)
    return na.valid and nb.valid and na.normalized == nb.normalized
