from app.crawler.types import CrawlArtifact, CrawlRequest, ParsedLink
from app.qa import evaluate
from app.qa.enums import OverallStatus, RelType


def test_qa_passes_when_link_found_and_clean():
    artifact = CrawlArtifact(
        request=CrawlRequest(
            source_url="https://publisher.test/page",
            target_url="https://acme.test/seo",
            expected_anchor_text="Acme SEO",
        ),
        http_status=200,
        final_url="https://publisher.test/page",
        content_type="text/html",
    )
    artifact.robots.source_allowed = True
    artifact.matched_links = [
        ParsedLink(
            href="https://acme.test/seo",
            resolved_url="https://acme.test/seo",
            normalized_url="https://acme.test/seo",
            anchor_text="Acme SEO",
        )
    ]
    artifact.found_in_raw = True

    result = evaluate(artifact)

    assert result.status == OverallStatus.PASS
    assert result.current_rel == RelType.DOFOLLOW
    assert result.link_found is True


def test_qa_fails_when_link_missing():
    artifact = CrawlArtifact(
        request=CrawlRequest(
            source_url="https://publisher.test/page",
            target_url="https://acme.test/seo",
        ),
        http_status=200,
        final_url="https://publisher.test/page",
        content_type="text/html",
    )
    artifact.robots.source_allowed = True

    result = evaluate(artifact)

    assert result.status == OverallStatus.FAIL
    assert any(issue.label.value == "LINK_MISSING" for issue in result.issues)


# ── Domain-scope matching (target = project main domain) ─────────────────────
from app.crawler.engine import CrawlEngine
from app.crawler.normalize import is_domain_root


def test_is_domain_root_distinguishes_root_from_deep_url():
    assert is_domain_root("https://limo.black/") is True
    assert is_domain_root("https://www.limo.black") is True
    assert is_domain_root("https://limo.black/services/airport") is False
    assert is_domain_root("https://limo.black/?id=5") is False  # genuine (non-tracking) query
    assert is_domain_root("https://limo.black/?ref=x") is True  # ?ref= is stripped as tracking


def test_match_links_domain_scope_accepts_any_page_on_main_domain():
    req = CrawlRequest(
        source_url="https://publisher.test/post",
        target_url="https://limo.black/",  # bare domain root → auto domain scope
    )
    assert req.domain_match() is True
    links = [
        ParsedLink(
            href="/svc",
            resolved_url="https://limo.black/services/airport",
            normalized_url="https://limo.black/services/airport",
        ),
        ParsedLink(
            href="/other",
            resolved_url="https://competitor.com/",
            normalized_url="https://competitor.com/",
        ),
    ]
    matched = CrawlEngine()._match_links(links, req)
    assert [m.normalized_url for m in matched] == ["https://limo.black/services/airport"]


def test_match_links_url_scope_requires_exact_target():
    req = CrawlRequest(
        source_url="https://publisher.test/post",
        target_url="https://acme.test/seo/audit",  # deep path → exact-URL scope
    )
    assert req.domain_match() is False
    links = [
        ParsedLink(
            href="/x",
            resolved_url="https://acme.test/seo/other",
            normalized_url="https://acme.test/seo/other",
        )
    ]
    assert CrawlEngine()._match_links(links, req) == []


def test_qa_domain_match_deep_link_found_without_normalization_warning():
    artifact = CrawlArtifact(
        request=CrawlRequest(
            source_url="https://publisher.test/page",
            target_url="https://limo.black/",
        ),
        http_status=200,
        final_url="https://publisher.test/page",
        content_type="text/html",
    )
    artifact.robots.source_allowed = True
    artifact.matched_links = [
        ParsedLink(
            href="https://limo.black/fleet",
            resolved_url="https://limo.black/fleet",
            normalized_url="https://limo.black/fleet",
            anchor_text="Limo Black",
        )
    ]
    artifact.found_in_raw = True

    result = evaluate(artifact)

    assert result.link_found is True
    assert not any(issue.code == "LNK-04" for issue in result.issues)
