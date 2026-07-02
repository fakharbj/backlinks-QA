"""Analytics filter builders — every clause must actually bind its params.

Regression guard: `:param::timestamptz` (a `::` cast directly after a bind name)
defeats SQLAlchemy text() parsing — the param silently never binds and Postgres
raises a syntax error at request time. Compile each whitelisted clause and assert
all declared params are recognized as bind params.
"""

from __future__ import annotations

from sqlalchemy import text

from app.services.analytics_service import _FILTERS

_SAMPLES = {
    "project_id": "00000000-0000-0000-0000-000000000000",
    "vendor_id": "00000000-0000-0000-0000-000000000000",
    "campaign_id": "00000000-0000-0000-0000-000000000000",
    "link_type_id": "00000000-0000-0000-0000-000000000000",
    "scoring_rule_version_id": "00000000-0000-0000-0000-000000000000",
    "score_min": 10,
    "score_max": 90,
    "link_found": True,
    "http_class": "4xx",
}


def test_every_filter_clause_binds_all_its_params():
    for key, builder in _FILTERS.items():
        built = builder(_SAMPLES.get(key, "2026-06-01"))
        if built is None:
            continue
        clause, params = built
        bound = set(text(clause)._bindparams.keys())
        missing = set(params) - bound
        assert not missing, f"filter '{key}' declares params {missing} that never bind in: {clause}"
