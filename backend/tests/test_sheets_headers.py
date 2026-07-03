"""Sheet header normalisation — duplicate/blank headers must never stop a sync.

Regression: after write-back adds result columns, sheets can end up with
duplicate or blank header cells; gspread's get_all_records refuses those and the
tab silently stopped syncing. ``_unique_headers`` de-duplicates instead.
"""

from __future__ import annotations

from app.integrations.google_sheets import _unique_headers


def test_unique_headers_dedupes_and_fills_blanks():
    raw = ["URL", "User", "", "URL", "LS Status", "LS Status", "  "]
    assert _unique_headers(raw) == [
        "URL", "User", "column_3", "URL_2", "LS Status", "LS Status_2", "column_7",
    ]


def test_unique_headers_plain_row_unchanged():
    raw = ["Source URL", "Target URL", "Anchor"]
    assert _unique_headers(raw) == ["Source URL", "Target URL", "Anchor"]
