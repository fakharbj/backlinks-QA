"""URL normalization tests (PRD §8.4 coverage map)."""

from app.crawler.normalize import normalize_url, registrable_domain, urls_match


def test_normalize_drops_tracking_lowercases_and_sorts_query():
    result = normalize_url("HTTPS://WWW.Example.COM:443/a/../b/?utm_source=x&z=2&a=1#frag")

    assert result.valid
    # www stripped, default port dropped, dot-segment resolved, lenient trailing
    # slash removed, tracking param dropped, query sorted, fragment removed.
    assert result.normalized == "https://example.com/b?a=1&z=2"
    assert result.registrable_domain == "example.com"
    assert result.had_www is True
    assert result.scheme == "https"


def test_significant_fragment_kept_bare_anchor_dropped():
    # Stateful/SPA fragments identify DISTINCT resources and must NOT dedup away
    # (e.g. smallpdf's #s=<uuid>); bare in-page anchors still normalize off.
    a = normalize_url("https://smallpdf.com/file#s=aaaaaaaa-1111").normalized
    b = normalize_url("https://smallpdf.com/file#s=bbbbbbbb-2222").normalized
    assert a == "https://smallpdf.com/file#s=aaaaaaaa-1111"
    assert a != b  # distinct fragments → distinct URLs (not duplicates)
    # Hash routes are kept too.
    assert normalize_url("https://app.example.com/#/dashboard").normalized.endswith("#/dashboard")
    assert normalize_url("https://app.example.com/#!/inbox").normalized.endswith("#!/inbox")
    # Bare anchor is still dropped → same page.
    assert normalize_url("https://x.com/p#section").normalized == "https://x.com/p"
    assert normalize_url("https://x.com/p#top").normalized == normalize_url("https://x.com/p").normalized


def test_normalize_resolves_relative_url():
    result = normalize_url("../target?b=2&a=1", base_url="https://example.com/path/page.html")

    assert result.valid
    assert result.normalized == "https://example.com/target?a=1&b=2"


def test_scheme_insensitive_match_for_dedup():
    # http and https normalise to the same resource (rule 2) so they dedup.
    assert urls_match("http://acme.com/x", "https://acme.com/x")


def test_lenient_trailing_slash_equivalence():
    # The point of lenient mode: /a and /a/ collapse to one canonical form.
    assert normalize_url("https://acme.com/a").normalized == normalize_url(
        "https://acme.com/a/"
    ).normalized


def test_strict_trailing_slash_distinguishes():
    a = normalize_url("https://acme.com/a", trailing_slash_policy="strict").normalized
    b = normalize_url("https://acme.com/a/", trailing_slash_policy="strict").normalized
    assert a != b


def test_www_and_non_www_match_but_recorded():
    assert urls_match("https://www.acme.com/p", "https://acme.com/p")


def test_idn_punycode_equivalence():
    unicode_form = normalize_url("https://münchen.de/page")
    puny_form = normalize_url("https://xn--mnchen-3ya.de/page")
    assert unicode_form.valid and puny_form.valid
    assert unicode_form.normalized == puny_form.normalized


def test_unsupported_scheme_is_invalid():
    assert normalize_url("mailto:hi@acme.com").valid is False
    assert normalize_url("javascript:alert(1)").valid is False


def test_registrable_domain_multilevel_tld():
    assert registrable_domain("a.b.example.co.uk") == "example.co.uk"
    assert registrable_domain("blog.acme.com") == "acme.com"


def test_root_path_keeps_single_slash():
    assert normalize_url("https://acme.com").normalized == "https://acme.com/"
    assert normalize_url("https://acme.com/").normalized == "https://acme.com/"
