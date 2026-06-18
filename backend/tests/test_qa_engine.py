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
