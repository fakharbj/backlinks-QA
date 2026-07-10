"""Domain enrichment (Phase 10 P2): robots rollup + band derivation, write-once
first-metrics snapshot, the new filter/sort/rule/export whitelists (kept in
lockstep), and the widened competitor-opportunity workflow vocabulary.

Pure tests exercise the extracted helpers (band ladder, snapshot guard, rule
validation, status transition rule) with no database. The integration tests
mirror ``test_source_domains_enterprise.py``: ``live_stack`` builds a throwaway
schema and skips cleanly when Postgres/Redis are unavailable.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.errors import ValidationAppError
from app.services import competitor_service
from app.services import source_domain_rule_service as rule_svc
from app.services import source_domain_service as sd_svc


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Robots band ladder (pure — mirrors the CASE in the recompute SQL)
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    ("allowed", "blocked", "band"),
    [
        (0, 0, "unknown"),            # nothing checked yet
        (0, 1, "fully_blocked"),      # blocked>0, allowed=0
        (0, 9, "fully_blocked"),
        (1, 2, "mostly_blocked"),     # blocked > allowed
        (2, 1, "partially_blocked"),  # blocked>0 but not the majority
        (1, 1, "partially_blocked"),  # tie is NOT "mostly"
        (3, 0, "allowed"),
    ],
)
def test_derive_robots_band(allowed, blocked, band):
    assert sd_svc.derive_robots_band(allowed, blocked) == band


def test_recompute_sql_carries_robots_columns():
    """Lockstep guard: the recompute upsert must write every robots column and
    keep them recompute-owned (present in the ON CONFLICT SET list too)."""
    sql = sd_svc._UPSERT.text
    for col in ("robots_allowed_count", "robots_blocked_count", "robots_unknown_count", "robots_band"):
        assert sql.count(col) >= 2, f"{col} missing from INSERT or ON CONFLICT SET"
    # Every band the pure helper can return must exist as a SQL literal.
    for band in sd_svc.ROBOTS_BANDS:
        assert f"'{band}'" in sql, f"band {band!r} missing from the SQL CASE"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. First-metrics snapshot guard (pure — attribute logic on any object)
# ═══════════════════════════════════════════════════════════════════════════════
def _stub_domain(**overrides):
    stub = SimpleNamespace(
        first_metrics_at=None, first_metrics_source=None,
        da_first=None, pa_first=None, spam_first=None, as_first=None,
        traffic_first=None,
    )
    for key, value in overrides.items():
        setattr(stub, key, value)
    return stub


def test_first_snapshot_records_first_values():
    sd = _stub_domain()
    taken = sd_svc.apply_first_snapshot(
        sd, {"da": 40, "pa": 33, "semrush_as": 20}, source="checked"
    )
    assert taken is True
    assert (sd.da_first, sd.pa_first, sd.as_first) == (40, 33, 20)
    assert sd.spam_first is None and sd.traffic_first is None  # absent stays NULL
    assert sd.first_metrics_at is not None
    assert sd.first_metrics_source == "checked"


def test_first_snapshot_never_overwrites():
    sd = _stub_domain()
    assert sd_svc.apply_first_snapshot(sd, {"da": 40}, source="imported")
    stamp = sd.first_metrics_at
    # A later, better fetch must NOT touch the originals.
    assert sd_svc.apply_first_snapshot(sd, {"da": 90, "pa": 80}, source="checked") is False
    assert sd.da_first == 40 and sd.pa_first is None
    assert sd.first_metrics_at is stamp
    assert sd.first_metrics_source == "imported"


def test_first_snapshot_skips_empty_payload():
    sd = _stub_domain()
    # No metric values at all (e.g. RDAP-only response) → no snapshot yet, so
    # the first REAL values can still win later.
    assert sd_svc.apply_first_snapshot(sd, {"domain_age_days": 900}, source="checked") is False
    assert sd.first_metrics_at is None and sd.first_metrics_source is None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Filter/sort/rule/export whitelists in lockstep
# ═══════════════════════════════════════════════════════════════════════════════
def test_whitelists_registered_in_lockstep():
    # *_first numeric ranges.
    for field in ("da_first", "pa_first", "spam_first", "as_first", "traffic_first"):
        assert field in sd_svc._NUMERIC_FILTER_COLUMNS
        assert f"{field}_min" in sd_svc._RANGE_PARAMS
        assert f"{field}_max" in sd_svc._RANGE_PARAMS
        assert field in sd_svc._SORT_COLUMNS
        assert field in rule_svc._ALL_FIELDS
    # String fields: filterable + rule-visible; robots_band also sortable.
    for field in ("robots_band", "market", "country"):
        assert field in sd_svc._STRING_FILTER_COLUMNS
        assert field in sd_svc._SORT_COLUMNS
        assert field in rule_svc._ALL_FIELDS
    exported = {key for _, key in sd_svc._EXPORT_COLUMNS}
    for key in (
        "robots_band", "robots_allowed_count", "robots_blocked_count",
        "robots_unknown_count", "da_first", "pa_first", "spam_first",
        "as_first", "traffic_first", "first_metrics_at", "market", "country",
    ):
        assert key in exported, f"{key} missing from _EXPORT_COLUMNS"


def test_build_filters_robots_band_whitelist():
    ctx = SimpleNamespace(workspace_id=uuid.uuid4())
    base = len(sd_svc._build_filters(ctx))
    # Comma multi-select of valid bands adds exactly one IN clause.
    clauses = sd_svc._build_filters(ctx, filters={"robots_band": "allowed,unknown"})
    assert len(clauses) == base + 1
    # market/country are free-text (case-insensitive) — accepted as-is.
    clauses = sd_svc._build_filters(ctx, filters={"market": "US,DE", "country": "Germany"})
    assert len(clauses) == base + 2
    # A non-whitelisted band value is rejected, never bound.
    with pytest.raises(ValidationAppError):
        sd_svc._build_filters(ctx, filters={"robots_band": "allowed,nope"})


def test_rule_definitions_accept_new_fields():
    ok = rule_svc._validate_definition(
        {
            "match": "all",
            "conditions": [
                {"field": "robots_band", "op": "==", "value_str": "fully_blocked"},
                {"field": "market", "op": "==", "value_str": "US"},
                {"field": "da_first", "op": ">=", "value": 30},
            ],
        }
    )
    assert len(ok["conditions"]) == 3
    # Unknown band value rejected.
    with pytest.raises(ValidationAppError):
        rule_svc._validate_definition(
            {"match": "all", "conditions": [{"field": "robots_band", "op": "==", "value_str": "nope"}]}
        )
    # String fields still only support '=='.
    with pytest.raises(ValidationAppError):
        rule_svc._validate_definition(
            {"match": "all", "conditions": [{"field": "market", "op": ">=", "value_str": "US"}]}
        )
    # Non-whitelisted fields stay rejected.
    with pytest.raises(ValidationAppError):
        rule_svc._validate_definition(
            {"match": "all", "conditions": [{"field": "robots_allowed_count; DROP", "op": ">=", "value": 1}]}
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Opportunity workflow vocabulary + transition rule (pure)
# ═══════════════════════════════════════════════════════════════════════════════
def test_opportunity_vocabulary_complete():
    required = {
        "new", "under_review", "validated", "approved", "rejected", "duplicate",
        "blocked", "needs_metrics", "needs_link_type_review", "ready", "assigned",
        "used", "archived",
    }
    assert required == set(competitor_service.OPPORTUNITY_STATUSES)
    # Legacy dismiss/re-open pair stays valid for filters AND manual set.
    assert {"open", "dismissed"} <= competitor_service.FILTERABLE_STATUSES
    assert {"open", "dismissed"} <= competitor_service.SETTABLE_STATUSES
    # Derived-only statuses are filterable/displayable but never settable.
    assert {"used", "duplicate"} <= competitor_service.FILTERABLE_STATUSES
    assert not ({"used", "duplicate"} & competitor_service.SETTABLE_STATUSES)


@pytest.mark.parametrize("derived", ["used", "duplicate", "USED ", "Duplicate"])
def test_derived_statuses_rejected(derived):
    with pytest.raises(ValidationAppError):
        competitor_service.validate_settable_status(derived)


def test_settable_statuses_normalized():
    assert competitor_service.validate_settable_status(" Under_Review ") == "under_review"
    with pytest.raises(ValidationAppError):
        competitor_service.validate_settable_status("not-a-status")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Integration — recompute rollup, list filter, export, status endpoint
# (live_stack skips when Postgres/Redis are unavailable)
# ═══════════════════════════════════════════════════════════════════════════════
def _register(client):
    email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": email, "password": "Password-12345",
            "full_name": "Admin", "workspace_name": "Enrichment Ws",
        },
    )
    assert reg.status_code == 201, reg.text
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def _make_project(client, h, target="acme-enrich.test"):
    proj = client.post(
        "/api/v1/projects",
        json={"name": "Enrich Proj", "target_domain": target},
        headers=h,
    )
    assert proj.status_code == 201, proj.text
    return proj.json()["id"]


@pytest.mark.integration
def test_recompute_robots_rollup_and_filter(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        project_id = _make_project(client, h)
        tag = uuid.uuid4().hex[:6]
        domain = f"robots-{tag}.test"
        for path in ("a", "b"):
            r = client.post(
                "/api/v1/backlinks",
                json={
                    "project_id": project_id,
                    "source_page_url": f"https://{domain}/{path}",
                    "target_url": "https://acme-enrich.test/x",
                },
                headers=h,
            )
            assert r.status_code == 201, r.text
        rec = client.post("/api/v1/source-domains/recompute", headers=h)
        assert rec.status_code == 200, rec.text

        # No QA ran → robots_status NULL on every row → the whole domain is
        # 'unknown' with all links in the unknown bucket.
        listed = client.get("/api/v1/source-domains", headers=h)
        assert listed.status_code == 200, listed.text
        row = {d["domain_key"]: d for d in listed.json()["items"]}[domain]
        assert row["backlink_count"] == 2

        # The band filter narrows: unknown keeps it, allowed drops it.
        unknown = client.get(
            "/api/v1/source-domains", params={"robots_band": "unknown"}, headers=h
        )
        assert domain in {d["domain_key"] for d in unknown.json()["items"]}
        allowed = client.get(
            "/api/v1/source-domains", params={"robots_band": "allowed"}, headers=h
        )
        assert domain not in {d["domain_key"] for d in allowed.json()["items"]}

        # A non-whitelisted band value is rejected (4xx, not a silent pass).
        bad = client.get(
            "/api/v1/source-domains", params={"robots_band": "nope"}, headers=h
        )
        assert 400 <= bad.status_code < 500, bad.text

        # Export carries the new columns.
        csv_resp = client.get(
            "/api/v1/source-domains/export", params={"format": "csv"}, headers=h
        )
        assert csv_resp.status_code == 200, csv_resp.text
        header_line = csv_resp.content.decode("utf-8-sig").splitlines()[0]
        assert "robots band" in header_line and "DA first" in header_line


@pytest.mark.integration
def test_opportunity_status_workflow(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        project_id = _make_project(client, h)
        tag = uuid.uuid4().hex[:6]
        opp_domain = f"blog-{tag}.test"
        ingest = client.post(
            "/api/v1/competitors/ingest",
            json={
                "project_id": project_id,
                "competitor_url": f"https://rival-{tag}.test",
                "name": "Rival",
                "text": f"https://{opp_domain}/post",
            },
            headers=h,
        )
        assert ingest.status_code == 201, ingest.text

        # Manual workflow status persists (side-table upsert).
        set_resp = client.patch(
            "/api/v1/competitors/opportunities/status",
            json={
                "project_id": project_id, "domain_key": opp_domain,
                "status": "under_review", "note": "checking DA first",
            },
            headers=h,
        )
        assert set_resp.status_code == 200, set_resp.text
        body = set_resp.json()
        assert body["status"] == "under_review"
        assert body["note"] == "checking DA first"

        # Derived-only statuses are rejected on manual set.
        for derived in ("used", "duplicate"):
            rej = client.patch(
                "/api/v1/competitors/opportunities/status",
                json={"project_id": project_id, "domain_key": opp_domain, "status": derived},
                headers=h,
            )
            assert 400 <= rej.status_code < 500, rej.text

        # Status filter narrows the opportunity list.
        hit = client.get(
            "/api/v1/competitors/domains",
            params={"project_id": project_id, "status": "under_review"},
            headers=h,
        )
        assert hit.status_code == 200, hit.text
        rows = {d["domain_key"]: d for d in hit.json()}
        assert opp_domain in rows
        assert rows[opp_domain]["decision"] == "under_review"

        miss = client.get(
            "/api/v1/competitors/domains",
            params={"project_id": project_id, "status": "archived"},
            headers=h,
        )
        assert opp_domain not in {d["domain_key"] for d in miss.json()}

        # A non-whitelisted filter value is rejected.
        bad = client.get(
            "/api/v1/competitors/domains",
            params={"project_id": project_id, "status": "nope"},
            headers=h,
        )
        assert 400 <= bad.status_code < 500, bad.text

        # Legacy dismiss/re-open still works through the old endpoint.
        dismissed = client.patch(
            "/api/v1/competitors/domains/decision",
            json={"project_id": project_id, "domain_key": opp_domain, "status": "dismissed"},
            headers=h,
        )
        assert dismissed.status_code == 200, dismissed.text
        assert dismissed.json()["dismissed"] == 1
