"""Relaxed GBP/GMB/citation matching (pure — no DB/network).

Owner rule: for GBP/GMB link types, when the main-domain link is absent, a Google
Maps/GBP listing link or an owned-directory link carrying the business tokens
counts as present — disclosed via LNK-18, never a silent exact-URL claim.
"""

from app.crawler.relaxed import business_tokens, find_relaxed_match
from app.crawler.types import CrawlArtifact, CrawlRequest, ParsedLink
from app.qa import evaluate
from app.qa.enums import OverallStatus


def _link(url: str) -> ParsedLink:
    return ParsedLink(href=url, resolved_url=url, normalized_url=url, anchor_text="x")


def test_maps_link_matches_and_plain_google_does_not():
    links = [
        _link("https://viewer.test/help"),
        _link("https://www.google.com/maps/place/Picture+Perfect+Glass"),
    ]
    hit = find_relaxed_match(links, tokens=[], owned_directories=[])
    assert hit is not None and hit[1] == "gbp_map"
    # A plain google.com link (search, docs) is NOT a listing.
    assert find_relaxed_match([_link("https://www.google.com/search?q=x")], tokens=[], owned_directories=[]) is None
    # g.page and business.site short listing links count.
    assert find_relaxed_match([_link("https://g.page/picture-perfect")], tokens=[], owned_directories=[])[1] == "gbp_map"
    assert find_relaxed_match([_link("https://picture-perfect.business.site/")], tokens=[], owned_directories=[])[1] == "gbp_map"


def test_owned_directory_requires_business_tokens():
    tokens = business_tokens("Picture Perfect Glass")
    links = [_link("https://citybizlocal.com/business/picture-perfect-glass-window-cleaning/")]
    hit = find_relaxed_match(links, tokens=tokens, owned_directories=["citybizlocal.com"])
    assert hit is not None and hit[1] == "owned_directory"
    # A DIFFERENT business on the same owned directory must NOT validate ours.
    other = [_link("https://citybizlocal.com/business/joes-plumbing/")]
    assert find_relaxed_match(other, tokens=tokens, owned_directories=["citybizlocal.com"]) is None
    # And without tokens the owned-directory rule never fires (no blind matches).
    assert find_relaxed_match(links, tokens=[], owned_directories=["citybizlocal.com"]) is None


def test_tokens_are_stoplisted_and_distinctive():
    toks = business_tokens("The Service Company Inc", "sunara solar")
    assert "the" not in toks and "inc" not in toks and "service" not in toks
    assert "sunara" in toks and "solar" in toks


def test_relaxed_verdict_is_found_with_disclosure():
    req = CrawlRequest(
        source_url="https://citations.test/listing", target_url="https://pictureperfectglass.com/",
        relaxed_match=True, business_tokens=["picture", "perfect", "glass"],
        owned_directory_domains=["citybizlocal.com"],
    )
    art = CrawlArtifact(request=req, http_status=200,
                        final_url="https://citations.test/listing", content_type="text/html")
    art.robots.source_allowed = True
    maps = _link("https://maps.google.com/?cid=123")
    art.all_links = [maps]
    art.matched_links = [maps]      # what the engine's relaxed fallback sets
    art.relaxed_reason = "gbp_map"
    result = evaluate(art)
    labels = {i.label.value for i in result.issues}
    codes = {i.code for i in result.issues}
    assert "LINK_MISSING" not in labels
    assert "LNK-18" in codes                       # the disclosure note
    assert result.status in (OverallStatus.PASS, OverallStatus.WARNING)
