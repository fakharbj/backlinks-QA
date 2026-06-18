from app.workers.tasks.reports import _display, _slug


def test_report_slug_is_filesystem_safe():
    assert _slug("Monthly QA: Acme / June") == "monthly-qa-acme-june"


def test_report_display_handles_none():
    assert _display(None) == ""
