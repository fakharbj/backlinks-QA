"""Final batch 4: public login-screen branding, standing-plan template cells
(upsert/delete with materialization), competitor metric enrichment fields,
provider-scoped source-domain metric fetch and backlink-row domain metrics."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.integration


def _register(client) -> dict:
    email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": email, "password": "Password-12345",
            "full_name": "Admin", "workspace_name": "Final Batch4 Ws",
        },
    )
    assert reg.status_code == 201, reg.text
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def test_public_branding_endpoint(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        up = client.put(
            "/api/v1/settings",
            json={
                "key": "branding",
                "value": {
                    "company_name": "Techsa QA",
                    "company_domain": "techsa-qa.test",
                    "logo_data_uri": None,
                },
                "is_secret": False,
            },
            headers=h,
        )
        assert up.status_code == 200, up.text

        # UNAUTHENTICATED — the login screen fetches this before any token
        # exists. Single-tenant style: the endpoint serves the first branding
        # row, which under parallel test workspaces may belong to another run —
        # so assert shape, not the exact name.
        pub = client.get("/api/v1/auth/branding")
        assert pub.status_code == 200, pub.text
        body = pub.json()
        assert isinstance(body["company_name"], str)
        assert "logo_data_uri" in body
        assert "company_domain" not in body  # never leaked publicly


def test_template_entry_upsert_and_delete(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        proj = client.post("/api/v1/projects", json={"name": "B4 Proj"}, headers=h)
        project_id = proj.json()["id"]
        label = f"tmpl-{uuid.uuid4().hex[:6]}"

        # Force today to be a working day (it may be a Sunday) so the
        # materialized plan is not excused.
        day = date.today()
        client.put(
            "/api/v1/workforce/calendar",
            json={"day": day.isoformat(), "is_working": True},
            headers=h,
        )

        weekday = day.weekday()  # 0=Mon … 6=Sun
        up = client.put(
            "/api/v1/workforce/templates/entry",
            json={
                "user_label": label, "weekday": weekday, "project_id": project_id,
                "hours": 2, "link_type_names": ["Article"], "priority": "high",
                "expected_links": 8,
            },
            headers=h,
        )
        assert up.status_code == 200, up.text
        assert up.json()["materialized_days"]  # lands in current (and next) week

        # The materialized assignment shows up in the day report for this week.
        week_from = day - timedelta(days=weekday)
        week_to = week_from + timedelta(days=6)
        rep = client.get(
            "/api/v1/workforce/day-report",
            params={
                "date_from": week_from.isoformat(), "date_to": week_to.isoformat(),
                "user_label": label,
            },
            headers=h,
        )
        assert rep.status_code == 200, rep.text
        mine = [r for r in rep.json() if r["day"] == day.isoformat()]
        assert mine and mine[0]["user_label"] == label and mine[0]["hours"] == 2.0

        # Delete the cell WITH its materialized assignments — plan row is gone.
        rm = client.delete(
            "/api/v1/workforce/templates/entry",
            params={
                "user_label": label, "weekday": weekday, "project_id": project_id,
                "remove_assignments": "true",
            },
            headers=h,
        )
        assert rm.status_code == 200, rm.text
        rep2 = client.get(
            "/api/v1/workforce/day-report",
            params={
                "date_from": week_from.isoformat(), "date_to": week_to.isoformat(),
                "user_label": label,
            },
            headers=h,
        )
        assert rep2.status_code == 200 and rep2.json() == []


def test_competitor_metric_enrichment_fields(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        proj = client.post("/api/v1/projects", json={"name": "B4 Comp"}, headers=h)
        project_id = proj.json()["id"]

        mark = uuid.uuid4().hex[:6]
        ing = client.post(
            "/api/v1/competitors/ingest",
            json={
                "project_id": project_id,
                "competitor_url": "rival-b4.test",
                "text": f"https://blog-{mark}.test/a\nhttps://blog-{mark}.test/b, anchor, dofollow, GP",
            },
            headers=h,
        )
        assert ing.status_code == 201, ing.text
        sheet_id = ing.json()["id"]

        # Per-sheet expand rows carry the metric + decision columns (no keys
        # configured in tests → values stay None / "open", but the keys exist).
        rows = client.get(f"/api/v1/competitors/sheets/{sheet_id}/backlinks", headers=h)
        assert rows.status_code == 200, rows.text
        assert rows.json()
        for r in rows.json():
            for key in ("url", "source_domain", "da", "pa", "semrush_as", "decision"):
                assert key in r, f"missing {key}"

        # Summary exposes the averages alongside the lifecycle counters.
        summ = client.get(
            "/api/v1/competitors/summary", params={"project_id": project_id}, headers=h
        )
        assert summ.status_code == 200, summ.text
        s = summ.json()
        for key in (
            "avg_da", "avg_as",
            "domains", "new_opportunities", "existing", "dismissed", "competitor_links",
        ):
            assert key in s, f"missing {key}"


def test_fetch_metrics_provider_param(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        # No Moz/Semrush keys are configured in the test env, so each call is a
        # harmless no-op — the contract under test is the provider scoping.
        for providers in ("moz", "semrush", "bogus"):
            r = client.post(
                "/api/v1/source-domains/fetch-metrics",
                params={"providers": providers},
                headers=h,
            )
            assert r.status_code == 200, (providers, r.text)


def test_backlink_row_exposes_domain_metrics(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        proj = client.post("/api/v1/projects", json={"name": "B4 Links"}, headers=h)
        project_id = proj.json()["id"]

        bl = client.post(
            "/api/v1/backlinks",
            json={
                "project_id": project_id,
                "source_page_url": f"https://blog-{uuid.uuid4().hex[:6]}.test/post",
                "target_url": "https://acme.test/",
            },
            headers=h,
        )
        assert bl.status_code == 201, bl.text

        lst = client.get("/api/v1/backlinks", params={"project_id": project_id}, headers=h)
        assert lst.status_code == 200, lst.text
        items = lst.json()["items"]
        assert items
        # Domain metrics ride along on every row (None until a fetch runs).
        assert "domain_da" in items[0]
