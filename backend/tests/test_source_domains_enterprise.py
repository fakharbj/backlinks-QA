"""Source-domain enterprise surface (0033): recompute-backed QA-outcome
aggregates (qualified/not-qualified/referring-domains), whitelisted range
filters + sorting, the set-based stats aggregate, the whitelisted Rules engine
(CRUD + apply + invalid-field rejection), per-workspace saved filters, and
CSV/XLSX export.

Harness mirrors ``test_batch_system.py``: the ``live_stack`` fixture builds a
throwaway schema (skips cleanly when Postgres/Redis are down), ``_register``
opens a fresh workspace via public registration (conftest opens signup), and a
``TestClient`` drives the real routers. No network — recompute + metrics checks
run inline; with no RapidAPI key configured, metric columns simply stay blank.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


def _register(client):
    email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": email, "password": "Password-12345",
            "full_name": "Admin", "workspace_name": "Source Domains Ws",
        },
    )
    assert reg.status_code == 201, reg.text
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def _make_project(client, h, target="acme-sd.test"):
    proj = client.post(
        "/api/v1/projects",
        json={"name": "SD Proj", "target_domain": target},
        headers=h,
    )
    assert proj.status_code == 201, proj.text
    return proj.json()["id"]


def _add_backlink(client, h, project_id, source_url, target_url):
    r = client.post(
        "/api/v1/backlinks",
        json={
            "project_id": project_id,
            "source_page_url": source_url,
            "target_url": target_url,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _override(client, h, backlink_id, status_value):
    r = client.post(
        f"/api/v1/backlinks/{backlink_id}/override",
        json={"status": status_value, "note": "test override"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _seed(client, h):
    """Two source domains with distinct QA outcomes, then recompute.

    good.test   → 2 links, both overridden PASS      → 2 qualified,  2 referring
    mixed.test  → 2 links, one PASS + one FAIL        → 1 qualified,  1 referring*

    *both mixed.test links point at the SAME target, so referring_domains_count
    (COUNT DISTINCT target_domain) is 1 for it and 2 for good.test.
    """
    project_id = _make_project(client, h)
    tag = uuid.uuid4().hex[:6]
    good = f"good-{tag}.test"
    mixed = f"mixed-{tag}.test"

    # good.test → two links to TWO DISTINCT target domains, both PASS
    # (referring_domains_count = COUNT DISTINCT target_domain = 2).
    b1 = _add_backlink(client, h, project_id, f"https://{good}/a", "https://acme-sd.test/x")
    b2 = _add_backlink(client, h, project_id, f"https://{good}/b", "https://other-sd.test/y")
    _override(client, h, b1["id"], "PASS")
    _override(client, h, b2["id"], "PASS")

    # mixed.test → two links, SAME target, one PASS + one FAIL.
    b3 = _add_backlink(client, h, project_id, f"https://{mixed}/a", "https://acme-sd.test/z")
    b4 = _add_backlink(client, h, project_id, f"https://{mixed}/b", "https://acme-sd.test/z")
    _override(client, h, b3["id"], "PASS")
    _override(client, h, b4["id"], "FAIL")

    rec = client.post("/api/v1/source-domains/recompute", headers=h)
    assert rec.status_code == 200, rec.text
    return {"project_id": project_id, "good": good, "mixed": mixed}


def _domains_by_key(client, h, **params):
    r = client.get("/api/v1/source-domains", params=params, headers=h)
    assert r.status_code == 200, r.text
    return {d["domain_key"]: d for d in r.json()["items"]}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Recompute-backed aggregates
# ═══════════════════════════════════════════════════════════════════════════════
def test_recompute_populates_qa_aggregates(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        seed = _seed(client, h)
        by_key = _domains_by_key(client, h)

        good = by_key[seed["good"]]
        assert good["backlink_count"] == 2
        assert good["qualified_count"] == 2
        assert good["not_qualified_count"] == 0
        assert good["qualified_pct"] == 100.0
        assert good["referring_domains_count"] == 2  # two distinct targets

        mixed = by_key[seed["mixed"]]
        assert mixed["backlink_count"] == 2
        assert mixed["qualified_count"] == 1          # one PASS
        assert mixed["not_qualified_count"] == 1      # one FAIL
        assert mixed["qualified_pct"] == 50.0
        assert mixed["referring_domains_count"] == 1  # both links share a target


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Whitelisted filters + sorting
# ═══════════════════════════════════════════════════════════════════════════════
def test_filters_and_sorting(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        seed = _seed(client, h)

        # Both seeded domains have >=1 qualified link.
        q1 = _domains_by_key(client, h, qualified_min=1)
        assert seed["good"] in q1 and seed["mixed"] in q1

        # qualified_min=2 narrows to only the fully-qualified domain.
        q2 = _domains_by_key(client, h, qualified_min=2)
        assert seed["good"] in q2 and seed["mixed"] not in q2

        # da_min with no metrics fetched (no API key in tests) → DA is NULL, so a
        # ``da >= N`` comparison matches nothing. The filter narrows to empty.
        da = _domains_by_key(client, h, da_min=1)
        assert seed["good"] not in da and seed["mixed"] not in da

        # Sorting by qualified_count is whitelisted and returns 200.
        r = client.get(
            "/api/v1/source-domains",
            params={"sort": "qualified_count", "order": "desc"},
            headers=h,
        )
        assert r.status_code == 200, r.text
        keys = [d["domain_key"] for d in r.json()["items"]]
        # good (2 qualified) sorts before mixed (1 qualified).
        assert keys.index(seed["good"]) < keys.index(seed["mixed"])

        # A non-whitelisted sort field falls back safely (still 200, no error).
        r2 = client.get(
            "/api/v1/source-domains",
            params={"sort": "drop table", "order": "desc"},
            headers=h,
        )
        assert r2.status_code == 200, r2.text


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Stats aggregate
# ═══════════════════════════════════════════════════════════════════════════════
def test_stats_shape_and_values(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        _seed(client, h)
        r = client.get("/api/v1/source-domains/stats", headers=h)
        assert r.status_code == 200, r.text
        s = r.json()

        for key in (
            "total_domains", "total_backlinks", "total_qualified",
            "overall_qualified_pct", "overall_indexed_pct",
            "avg_da", "avg_pa", "avg_spam", "avg_as",
            "count_da_ge_50", "count_spam_le_5", "count_indexed",
        ):
            assert key in s, f"missing stats key {key}"

        assert s["total_domains"] == 2
        assert s["total_backlinks"] == 4        # 2 + 2
        assert s["total_qualified"] == 3        # 2 (good) + 1 (mixed)
        assert s["overall_qualified_pct"] == 75.0  # 3 / 4
        # No metrics fetched → averages are null.
        assert s["avg_da"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Rules engine (CRUD + apply + invalid field)
# ═══════════════════════════════════════════════════════════════════════════════
def test_rules_engine_lifecycle(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        seed = _seed(client, h)

        # Create a rule: qualified_count >= 1.
        created = client.post(
            "/api/v1/source-domains/rules",
            json={
                "name": "Has a qualified link",
                "definition": {
                    "match": "all",
                    "conditions": [
                        {"field": "qualified_count", "op": ">=", "value": 1}
                    ],
                },
            },
            headers=h,
        )
        assert created.status_code == 201, created.text
        rule_id = created.json()["id"]

        # List includes it.
        listed = client.get("/api/v1/source-domains/rules", headers=h)
        assert listed.status_code == 200, listed.text
        assert any(r["id"] == rule_id for r in listed.json())

        # Apply → both seeded domains match (each has >=1 qualified).
        applied = client.get(f"/api/v1/source-domains/rules/{rule_id}/apply", headers=h)
        assert applied.status_code == 200, applied.text
        body = applied.json()
        got = {d["domain_key"] for d in body["items"]}
        assert seed["good"] in got and seed["mixed"] in got
        assert body["match_count"] == body["total"] >= 2

        # Tighten via PATCH: qualified_count >= 2 → only good.test.
        patched = client.patch(
            f"/api/v1/source-domains/rules/{rule_id}",
            json={
                "definition": {
                    "match": "all",
                    "conditions": [
                        {"field": "qualified_count", "op": ">=", "value": 2}
                    ],
                }
            },
            headers=h,
        )
        assert patched.status_code == 200, patched.text
        applied2 = client.get(
            f"/api/v1/source-domains/rules/{rule_id}/apply", headers=h
        ).json()
        got2 = {d["domain_key"] for d in applied2["items"]}
        assert seed["good"] in got2 and seed["mixed"] not in got2

        # Invalid (non-whitelisted) field is rejected on create → 4xx.
        bad = client.post(
            "/api/v1/source-domains/rules",
            json={
                "name": "Bad field",
                "definition": {
                    "match": "all",
                    "conditions": [
                        {"field": "; DROP TABLE", "op": ">=", "value": 1}
                    ],
                },
            },
            headers=h,
        )
        assert 400 <= bad.status_code < 500, bad.text

        # Delete removes it.
        deleted = client.delete(f"/api/v1/source-domains/rules/{rule_id}", headers=h)
        assert deleted.status_code == 200, deleted.text
        listed2 = client.get("/api/v1/source-domains/rules", headers=h).json()
        assert not any(r["id"] == rule_id for r in listed2)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Saved filters
# ═══════════════════════════════════════════════════════════════════════════════
def test_saved_filters_roundtrip(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)

        put = client.put(
            "/api/v1/source-domains/saved-filters",
            json={"name": "High DA", "params": {"da_min": "50"}},
            headers=h,
        )
        assert put.status_code == 200, put.text
        assert any(f["name"] == "High DA" for f in put.json())

        got = client.get("/api/v1/source-domains/saved-filters", headers=h)
        assert got.status_code == 200, got.text
        match = [f for f in got.json() if f["name"] == "High DA"]
        assert match and match[0]["params"] == {"da_min": "50"}

        # DELETE (name as query param) removes it.
        deleted = client.delete(
            "/api/v1/source-domains/saved-filters",
            params={"name": "High DA"},
            headers=h,
        )
        assert deleted.status_code == 200, deleted.text
        assert not any(f["name"] == "High DA" for f in deleted.json())


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Export (CSV + XLSX)
# ═══════════════════════════════════════════════════════════════════════════════
def test_export_csv_and_xlsx(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        _seed(client, h)

        csv_resp = client.get(
            "/api/v1/source-domains/export", params={"format": "csv"}, headers=h
        )
        assert csv_resp.status_code == 200, csv_resp.text
        assert "text/csv" in csv_resp.headers["content-type"]
        text = csv_resp.content.decode("utf-8-sig")
        header_line = text.splitlines()[0]
        assert "domain" in header_line  # header row present

        xlsx_resp = client.get(
            "/api/v1/source-domains/export", params={"format": "xlsx"}, headers=h
        )
        assert xlsx_resp.status_code == 200, xlsx_resp.text
        assert (
            "spreadsheetml" in xlsx_resp.headers["content-type"]
            or "officedocument" in xlsx_resp.headers["content-type"]
        )
        assert xlsx_resp.content[:2] == b"PK"  # xlsx is a zip container
