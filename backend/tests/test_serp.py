"""Index-check SERP parsing tests (Phase 4).

Covers the pure verdict logic so it's verifiable without hitting Google.
"""

from app.integrations import serp
from app.models.index_check import INDEXED, NOT_INDEXED, UNCERTAIN


def test_non_200_is_uncertain():
    v, c, _ = serp.classify_serp_html(429, "<html>too many</html>")
    assert v == UNCERTAIN


def test_empty_body_is_uncertain():
    v, _, _ = serp.classify_serp_html(200, "")
    assert v == UNCERTAIN


def test_block_markers_are_uncertain_not_negative():
    html = "<html><body>" + ("x" * 300) + " our systems have detected unusual traffic</body></html>"
    v, _, reason = serp.classify_serp_html(200, html)
    assert v == UNCERTAIN
    assert reason == "blocked_or_consent"


def test_consent_wall_is_uncertain():
    html = "<html>" + ("x" * 300) + " before you continue to Google </html>"
    v, _, _ = serp.classify_serp_html(200, html)
    assert v == UNCERTAIN


def test_zero_results_is_not_indexed():
    html = "<html><body>" + ("x" * 300) + " did not match any documents.</body></html>"
    v, c, _ = serp.classify_serp_html(200, html)
    assert v == NOT_INDEXED
    assert c == 0


def test_results_present_is_indexed():
    html = (
        '<html><body><div id="search"><div class="result-stats">About 12 results</div>'
        '<h3>A page</h3><a href="/url?q=https://example.com/post">link</a>'
        + ("<div>filler result snippet</div>" * 10)  # real SERP pages are large
        + "</div></body></html>"
    )
    v, c, _ = serp.classify_serp_html(200, html)
    assert v == INDEXED
    assert c == 12


def test_unrecognised_page_is_uncertain():
    html = "<html><body>" + ("z" * 300) + " something unexpected </body></html>"
    v, _, reason = serp.classify_serp_html(200, html)
    assert v == UNCERTAIN
    assert reason == "unrecognised_page"


def test_parse_result_count():
    assert serp.parse_result_count("About 1,234 results") == 1234
    assert serp.parse_result_count("no count here") is None


# ── DataForSEO SERP payload parsing (pure) ───────────────────────────────────
def _dfs_ok(items, se_count=None):
    result = {"items": items}
    if se_count is not None:
        result["se_results_count"] = se_count
    return {"status_code": 20000, "tasks": [{"status_code": 20000, "result": [result]}]}


def test_dataforseo_http_error_is_uncertain():
    v, _, _ = serp.classify_dataforseo_payload(402, {})
    assert v == UNCERTAIN


def test_dataforseo_api_error_is_uncertain():
    v, _, reason = serp.classify_dataforseo_payload(200, {"status_code": 40200, "tasks": []})
    assert v == UNCERTAIN
    assert reason.startswith("api_")


def test_dataforseo_task_error_is_uncertain():
    payload = {"status_code": 20000, "tasks": [{"status_code": 40501, "result": None}]}
    v, _, reason = serp.classify_dataforseo_payload(200, payload)
    assert v == UNCERTAIN
    assert reason.startswith("task_")


def test_dataforseo_no_result_block_is_not_indexed():
    payload = {"status_code": 20000, "tasks": [{"status_code": 20000, "result": None}]}
    v, c, _ = serp.classify_dataforseo_payload(200, payload)
    assert v == NOT_INDEXED
    assert c == 0


def test_dataforseo_organic_present_is_indexed():
    items = [{"type": "organic", "url": "https://example.com/post"}]
    v, c, _ = serp.classify_dataforseo_payload(200, _dfs_ok(items, se_count=7))
    assert v == INDEXED
    assert c == 7


def test_dataforseo_organic_present_without_count_falls_back_to_len():
    items = [{"type": "organic"}, {"type": "organic"}]
    v, c, _ = serp.classify_dataforseo_payload(200, _dfs_ok(items))
    assert v == INDEXED
    assert c == 2


def test_dataforseo_no_organic_items_is_not_indexed():
    items = [{"type": "people_also_ask"}]
    v, c, _ = serp.classify_dataforseo_payload(200, _dfs_ok(items))
    assert v == NOT_INDEXED
    assert c == 0
