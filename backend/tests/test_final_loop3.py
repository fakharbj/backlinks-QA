"""Final-pass Loop 3 tests: competitor parser (SEMrush headers, quoted commas,
GP tag), URL-required ingest, honest per-upload new/seen-before accounting,
guest-post filtering and sortable/searchable domain list."""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


def test_parse_competitor_text_semrush_and_plain():
    from app.services.competitor_service import parse_competitor_text

    semrush = (
        "Source url,Anchor,Nofollow,Link type,Page ascore\n"
        '"https://blog.example.com/a,b-post","best, tools",FALSE,Guest Post,42\n'
        "https://dir.example.com/listing,resources,TRUE,GP,10\n"
        "no-scheme.example.com/x,,FALSE,Article,5\n"
    )
    parsed = parse_competitor_text(semrush)
    assert parsed["format"] == "semrush"
    assert parsed["mapping"]["source url"] == "url"
    rows = parsed["rows"]
    assert len(rows) == 3
    # Quoted commas survive; anchor keeps its comma.
    assert rows[0][0] == "https://blog.example.com/a,b-post"
    assert rows[0][1] == "best, tools"
    assert rows[0][2] == "dofollow" and rows[0][3] == "Guest Post"
    # Nofollow column TRUE → rel nofollow; GP link type preserved.
    assert rows[1][2] == "nofollow" and rows[1][3] == "GP"
    # Scheme added automatically.
    assert rows[2][0].startswith("https://no-scheme.example.com")

    plain = "https://a.test/x, my anchor, dofollow, Article\nb.test/y\n"
    p2 = parse_competitor_text(plain)
    assert p2["format"] == "plain" and len(p2["rows"]) == 2
    assert p2["rows"][0][1] == "my anchor"


def test_competitor_ingest_counts_and_domains(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
        reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": email, "password": "Password-12345",
                "full_name": "QA Specialist", "workspace_name": "Final Loop3 Ws",
            },
        )
        assert reg.status_code == 201, reg.text
        headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
        proj = client.post("/api/v1/projects", json={"name": "Loop3 Proj"}, headers=headers)
        project_id = proj.json()["id"]

        # competitor_url is REQUIRED.
        bad = client.post(
            "/api/v1/competitors/ingest",
            json={"project_id": project_id, "text": "https://x.test/a"},
            headers=headers,
        )
        assert bad.status_code == 422

        mark = uuid.uuid4().hex[:6]
        first = client.post(
            "/api/v1/competitors/ingest",
            json={
                "project_id": project_id,
                "competitor_url": "rival-limo.test",
                "text": f"https://blog-{mark}.test/a\nhttps://blog-{mark}.test/b, anchor, dofollow, GP",
            },
            headers=headers,
        )
        assert first.status_code == 201, first.text
        f = first.json()
        # Name falls back to the competitor domain; counts are per-upload.
        assert f["name"] == "rival-limo.test"
        assert f["competitor_url"]
        assert f["total_rows"] == 2 and f["new_domains"] == 1 and f["existing_domains"] == 0

        # Second upload with ONE repeat domain + one new: honest split (the old
        # bug reported project-wide totals: 'existing 0 / new 21').
        second = client.post(
            "/api/v1/competitors/ingest",
            json={
                "project_id": project_id,
                "competitor_url": "https://rival-limo.test",
                "name": "Rival again",
                "text": f"https://blog-{mark}.test/c\nhttps://fresh-{mark}.test/1",
            },
            headers=headers,
        )
        assert second.status_code == 201, second.text
        s = second.json()
        assert s["new_domains"] == 1 and s["existing_domains"] == 1

        # GP tag counts as guest post → excluded when the toggle is on.
        all_domains = client.get(
            "/api/v1/competitors/domains",
            params={"project_id": project_id},
            headers=headers,
        ).json()
        gp_flagged = [d for d in all_domains if d["has_guest_post"]]
        assert any(d["domain_key"] == f"blog-{mark}.test" for d in gp_flagged)
        without_gp = client.get(
            "/api/v1/competitors/domains",
            params={"project_id": project_id, "exclude_guest_posts": "true"},
            headers=headers,
        ).json()
        assert all(d["domain_key"] != f"blog-{mark}.test" for d in without_gp)

        # Search + whitelisted sorting work.
        found = client.get(
            "/api/v1/competitors/domains",
            params={"project_id": project_id, "search": f"fresh-{mark}", "sort": "links", "direction": "desc"},
            headers=headers,
        )
        assert found.status_code == 200, found.text
        assert [d["domain_key"] for d in found.json()] == [f"fresh-{mark}.test"]

        # Per-domain expand-in-place data.
        links = client.get(
            "/api/v1/competitors/domain-backlinks",
            params={"project_id": project_id, "domain": f"blog-{mark}.test"},
            headers=headers,
        )
        assert links.status_code == 200 and len(links.json()) == 3
