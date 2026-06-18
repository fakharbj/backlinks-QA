"""Bot-protection / soft-404 / parked-page detection (BOT-*, PRD §8.6 N).

We never bypass protection — we *detect* it so the QA engine can route the link to
NEEDS_MANUAL_REVIEW instead of silently failing it (PRD §3.4, §9.6).
"""

from __future__ import annotations

import re

from app.crawler.types import DetectionFlags, PageSignals

_CAPTCHA_MARKERS = (
    "g-recaptcha", "h-captcha", "hcaptcha", "recaptcha", "captcha-delivery",
    "please verify you are a human", "verify you are human", "i'm not a robot",
    "px-captcha", "funcaptcha", "arkoselabs",
)
_CLOUDFLARE_MARKERS = (
    "cf-browser-verification", "checking your browser before accessing",
    "cf-challenge", "just a moment", "cf_chl_opt", "__cf_chl", "ray id",
    "enable javascript and cookies to continue",
)
_WAF_SIGNATURES = {
    "akamai": ("akamai", "reference&#32;", "access denied"),
    "incapsula": ("incapsula", "imperva", "_incap_", "visid_incap"),
    "sucuri": ("sucuri", "cloudproxy", "access denied - sucuri website firewall"),
    "modsecurity": ("mod_security", "modsecurity", "not acceptable!"),
    "aws_waf": ("aws waf", "request blocked", "awswaf"),
    "f5": ("the requested url was rejected", "bigip", "support id"),
}
_SOFT_404_MARKERS = (
    "404", "not found", "page not found", "page doesn't exist",
    "page does not exist", "no longer available", "page you requested",
    "the page you are looking for", "nothing found", "error 404",
)
_PARKED_MARKERS = (
    "domain is for sale", "buy this domain", "this domain may be for sale",
    "domain parking", "parkingcrew", "sedoparking", "this domain is parked",
    "the domain has expired", "domain for sale", "hugedomains",
)


def _has_any(haystack: str, needles) -> str | None:
    for n in needles:
        if n in haystack:
            return n
    return None


def detect(
    *,
    status: int | None,
    headers: dict[str, str],
    body: str,
    signals: PageSignals,
) -> DetectionFlags:
    flags = DetectionFlags()
    low = (body or "").lower()
    server = (headers.get("server") or "").lower()
    title_h1 = " ".join(filter(None, [signals.title or "", signals.h1 or ""])).lower()

    # CAPTCHA -----------------------------------------------------------------
    if (m := _has_any(low, _CAPTCHA_MARKERS)) is not None:
        flags.captcha = True
        flags.signature = m

    # Cloudflare challenge ----------------------------------------------------
    if "cloudflare" in server or _has_any(low, _CLOUDFLARE_MARKERS):
        if status in (403, 429, 503) or _has_any(low, _CLOUDFLARE_MARKERS):
            flags.cloudflare_challenge = True
            flags.signature = flags.signature or "cloudflare"

    # Generic WAF block -------------------------------------------------------
    if status in (403, 406, 429) or "access denied" in low:
        for vendor, sigs in _WAF_SIGNATURES.items():
            if _has_any(low, sigs) or _has_any(server, sigs):
                flags.waf_block = True
                flags.signature = flags.signature or vendor
                break

    # Empty page --------------------------------------------------------------
    if status == 200 and signals.word_count == 0 and len(low.strip()) < 60:
        flags.empty_page = True

    # Parked / expired domain -------------------------------------------------
    if (m := _has_any(low, _PARKED_MARKERS)) is not None:
        flags.parked = True
        flags.signature = flags.signature or m

    # Soft-404: 200 OK but the page declares "not found" and is thin ----------
    if status == 200 and not flags.captcha and not flags.cloudflare_challenge:
        title_says_404 = _has_any(title_h1, _SOFT_404_MARKERS) is not None
        body_says_404 = bool(re.search(r"\b404\b|\bpage not found\b", low))
        if title_says_404 or (body_says_404 and signals.word_count < 150) or flags.parked:
            flags.soft_404 = True
            flags.signature = flags.signature or "soft-404"

    return flags
