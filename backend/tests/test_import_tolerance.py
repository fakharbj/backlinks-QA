"""Sheet-import tolerance (owner rules).

1) Scheme-less URLs from sheets ("open.substack.com/pub/x") are real links —
   repaired with https://, never errored as unsupported_scheme.
2) Broken header cells ("#REF!", blank→column_N) hide the user column from
   name-based mapping — content inference finds it so links keep assignees.
"""

from __future__ import annotations

from app.services.import_parse import infer_user_column
from app.services.import_service import coerce_url_scheme, looks_like_url


def test_schemeless_url_is_repaired():
    assert coerce_url_scheme(
        "open.substack.com/pub/salasservices/p/diy-vs-professional-tree-trimming"
    ) == "https://open.substack.com/pub/salasservices/p/diy-vs-professional-tree-trimming"
    assert coerce_url_scheme("www.example.com") == "https://www.example.com"
    assert coerce_url_scheme("example.com/path?q=1") == "https://example.com/path?q=1"


def test_schemed_and_garbage_untouched():
    assert coerce_url_scheme("https://a.com/x") == "https://a.com/x"
    assert coerce_url_scheme("mailto:x@y.com") == "mailto:x@y.com"
    assert coerce_url_scheme("just some words") == "just some words"
    assert coerce_url_scheme("") == ""
    assert coerce_url_scheme("Pending") == "Pending"


def test_plain_text_source_is_ignored_not_errored():
    # A title/note in the source column = normal sheet formatting → the row is
    # SKIPPED quietly (green), never "Invalid source URL (unsupported_scheme)".
    assert not looks_like_url("5 Smart Reasons to Hire a Professional Service")
    assert not looks_like_url("Pending")
    assert not looks_like_url("")
    assert not looks_like_url("mailto:x@y.com")
    # Real (coerced) links still crawl.
    assert looks_like_url("https://a.com/x")
    assert looks_like_url(coerce_url_scheme("open.substack.com/pub/x/p/y"))
    assert looks_like_url("HTTP://UPPER.example")


def test_infer_user_column_finds_ref_header():
    # The real Legacy Roofing case: user column header is "#REF!" (dead
    # formula); names repeat down the column. Mapping lacks a user field.
    headers = ["#REF!", "Date", "Live Link", "Remarks"]
    mapping = {"Date": "sheet_created_date", "Live Link": "source_page_url"}
    rows = [
        {"#REF!": "Alex", "Date": "16-July-2026", "Live Link": "https://a.com/1", "Remarks": "done well"},
        {"#REF!": "Alex", "Date": "16-July-2026", "Live Link": "https://a.com/2", "Remarks": ""},
        {"#REF!": "Junius", "Date": "17-July-2026", "Live Link": "https://a.com/3", "Remarks": "checked ok fine"},
        {"#REF!": "Junius", "Date": "17-July-2026", "Live Link": "https://a.com/4", "Remarks": ""},
        {"#REF!": "Mark", "Date": "17-July-2026", "Live Link": "https://a.com/5", "Remarks": ""},
        {"#REF!": "Mark", "Date": "17-July-2026", "Live Link": "https://a.com/6", "Remarks": ""},
    ]
    m, inferred = infer_user_column(mapping, headers, rows)
    assert inferred == "#REF!"
    assert m["#REF!"] == "assigned_user_label"


def test_infer_skips_when_user_already_mapped():
    headers = ["User", "Live Link"]
    mapping = {"User": "assigned_user_label", "Live Link": "source_page_url"}
    rows = [{"User": "Alex", "Live Link": "https://a.com"}] * 5
    m, inferred = infer_user_column(mapping, headers, rows)
    assert inferred is None and m == mapping


def test_infer_never_picks_status_or_date_columns():
    # "Indexation" values look name-like ("Indexed") — the stopword guard
    # must reject it; dates contain digits so NAMEISH rejects them anyway.
    headers = ["Indexation", "Date", "Live Link"]
    mapping = {"Live Link": "source_page_url"}
    rows = [
        {"Indexation": "Indexed", "Date": "16-July-2026", "Live Link": "https://a.com/1"},
        {"Indexation": "Indexed", "Date": "16-July-2026", "Live Link": "https://a.com/2"},
        {"Indexation": "Pending", "Date": "17-July-2026", "Live Link": "https://a.com/3"},
        {"Indexation": "Pending", "Date": "17-July-2026", "Live Link": "https://a.com/4"},
    ]
    m, inferred = infer_user_column(mapping, headers, rows)
    assert inferred is None
    assert "assigned_user_label" not in m.values()


def test_infer_rejects_free_text_columns():
    # High-cardinality free text (every value different) is not a roster.
    headers = ["colX", "Live Link"]
    mapping = {"Live Link": "source_page_url"}
    rows = [{"colX": f"Something {i} entirely", "Live Link": f"https://a.com/{i}"} for i in range(10)]
    m, inferred = infer_user_column(mapping, headers, rows)
    assert inferred is None
