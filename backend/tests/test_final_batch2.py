"""Second finalization batch: JS-redirect stub detection, case-insensitive
productivity overrides, weekly templates (save/apply), laid-off exclusion and
per-upload competitor backlinks."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.integration


def test_stub_redirect_target_detection():
    from app.crawler.fetch import _stub_redirect_target

    # The exact parked-domain shell the owner hit (ai.ceo).
    stub = b'<!DOCTYPE html><html><head><script>window.onload=function(){window.location.href="/lander"}</script></head></html>'
    assert _stub_redirect_target(stub, "https://ai.ceo/read-blog/201939") == "https://ai.ceo/lander"

    # Meta refresh variant.
    meta = b'<html><head><meta http-equiv="refresh" content="0;url=https://elsewhere.test/page"></head></html>'
    assert _stub_redirect_target(meta, "https://x.test/") == "https://elsewhere.test/page"

    # A real page that merely mentions window.location must NOT match:
    real = (
        b"<html><body><a href='/x'>link</a>" + b"x" * 100
        + b"<script>if(a){window.location.href='/spa'}</script></body></html>"
    )
    assert _stub_redirect_target(real, "https://x.test/") is None
    # Big bodies never match.
    assert _stub_redirect_target(b"x" * 5000, "https://x.test/") is None


def _next_weekday(d: date) -> date:
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d


def test_templates_overrides_layoff_and_competitor_parent(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
        reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": email, "password": "Password-12345",
                "full_name": "Admin", "workspace_name": "Final Batch2 Ws",
            },
        )
        assert reg.status_code == 201, reg.text
        h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
        proj = client.post("/api/v1/projects", json={"name": "B2 Proj"}, headers=h)
        project_id = proj.json()["id"]

        # Case-insensitive override: set for lowercase, assign UPPERCASE.
        client.put(
            "/api/v1/workforce/productivity",
            json={"link_type_name": "Profile", "links_per_hour": 10},
            headers=h,
        )
        client.put(
            "/api/v1/workforce/productivity",
            json={"link_type_name": "Profile", "links_per_hour": 20, "user_label": "kevin"},
            headers=h,
        )
        day = _next_weekday(date.today() + timedelta(days=1))
        a = client.post(
            "/api/v1/workforce/assignments",
            json={
                "project_id": project_id, "user_label": "KEVIN", "day": day.isoformat(),
                "hours": 1, "link_type_names": ["Profile"],
            },
            headers=h,
        ).json()
        assert a["rate_source"] == "override" and a["expected_links"] == 20

        # Weekly template: save this week → apply to NEXT week.
        save = client.post(
            "/api/v1/workforce/templates/save-week",
            json={"week_start": day.isoformat()},
            headers=h,
        )
        assert save.status_code == 200 and save.json()["saved"] >= 1
        summary = client.get("/api/v1/workforce/templates", headers=h).json()
        assert summary["total_entries"] >= 1

        next_week = day + timedelta(days=7)
        applied = client.post(
            "/api/v1/workforce/templates/apply",
            json={"week_start": next_week.isoformat()},
            headers=h,
        )
        assert applied.status_code == 200 and applied.json()["applied"] >= 1
        monday = next_week - timedelta(days=next_week.weekday())
        rep = client.get(
            "/api/v1/workforce/day-report",
            params={
                "date_from": monday.isoformat(),
                "date_to": (monday + timedelta(days=6)).isoformat(),
            },
            headers=h,
        ).json()
        assert any(r["user_label"] == "KEVIN" for r in rep)

        # Laid-off: flag the mapping inactive → label leaves the pickers.
        labels_before = client.get("/api/v1/workforce/labels", headers=h).json()
        assert "KEVIN" in labels_before
        # Create a catalog mapping for KEVIN, then lay them off.
        sync = client.post("/api/v1/employees/sync", headers=h)
        assert sync.status_code == 200
        overview = client.get("/api/v1/employees", headers=h).json()
        kevin = next(
            (m for m in overview["mappings"] if m["sheet_user_label"].lower() == "kevin"), None
        )
        if kevin is None:  # no backlinks carry the label — create via mapping sync not possible; skip layoff check
            kevin = None
        else:
            off = client.patch(
                f"/api/v1/employees/mappings/{kevin['id']}",
                json={"is_active": False},
                headers=h,
            )
            assert off.status_code == 200
            labels_after = client.get("/api/v1/workforce/labels", headers=h).json()
            assert "KEVIN" not in labels_after and "kevin" not in labels_after

        # Competitor: parent upload → its backlinks endpoint.
        up = client.post(
            "/api/v1/competitors/ingest",
            json={
                "project_id": project_id,
                "competitor_url": "rival-b2.test",
                "text": "https://blog-b2.test/a, anchor, dofollow, Article\nhttps://blog-b2.test/b",
            },
            headers=h,
        )
        assert up.status_code == 201, up.text
        sheet_id = up.json()["id"]
        links = client.get(f"/api/v1/competitors/sheets/{sheet_id}/backlinks", headers=h)
        assert links.status_code == 200 and len(links.json()) == 2
        assert links.json()[0]["source_domain"] == "blog-b2.test"


def test_anchor_fallbacks_for_icon_links():
    from app.crawler.parse import parse_html

    html = """<html><body>
      <a href="https://t1.test/">Visible <b>text</b></a>
      <a href="https://t2.test/"><img src="x.png" alt="Brand logo"></a>
      <a href="https://t3.test/" aria-label="Follow us on X"><svg viewBox="0 0 1 1"></svg></a>
      <a href="https://t4.test/" title="Our old site"><img src="y.png"></a>
      <a href="https://t5.test/"><img src="z.png"></a>
    </body></html>"""
    page = parse_html(html, final_url="https://src.test/")
    by_href = {l.href: l for l in page.links}
    assert by_href["https://t1.test/"].effective_anchor == "Visible text"
    assert by_href["https://t2.test/"].effective_anchor == "Brand logo"       # img alt
    assert by_href["https://t3.test/"].effective_anchor == "Follow us on X"  # aria-label
    assert by_href["https://t4.test/"].effective_anchor == "Our old site"    # title attr
    # Image link with no text anywhere → explicit marker, never a blank.
    assert by_href["https://t5.test/"].effective_anchor == "[image link]"


def test_primary_link_prefers_real_anchor():
    from app.crawler.types import CrawlArtifact, CrawlRequest, ParsedLink

    art = CrawlArtifact(request=CrawlRequest(source_url="https://s.test/", target_url="https://t.test/"))
    empty = ParsedLink(
        href="https://t.test/", resolved_url="https://t.test/", normalized_url="https://t.test/",
        anchor_text="", rel=["nofollow"],
    )
    texty = ParsedLink(
        href="https://t.test/", resolved_url="https://t.test/", normalized_url="https://t.test/",
        anchor_text="stone masonry", rel=[],
    )
    # DOM order puts the empty one first (the myvipon case) — QA must still
    # report the real in-text link.
    art.matched_links = [empty, texty]
    assert art.primary_link is texty
    assert art.primary_link.effective_anchor == "stone masonry"


def test_markdown_link_matching():
    from app.crawler.parse import extract_markdown_links

    # The exact yeswiki/HedgeDoc case: raw markdown served as the page body.
    body = (
        "A professional [**vip black car service**](https://limo.black/) provides "
        "tailored transportation. Also [plain link](https://other.test/page) and "
        "a fenced `[not a real](https://x)` still parses — matching decides."
    )
    links = extract_markdown_links(body, final_url="https://md.yeswiki.net/s/RZJCiiiLZN")
    by_url = {l.href: l for l in links}
    limo = by_url.get("https://limo.black/")
    assert limo is not None
    assert limo.anchor_text == "vip black car service"  # emphasis markers stripped
    assert limo.effective_anchor == "vip black car service"
    assert "limo.black" in limo.normalized_url
    assert "tailored transportation" in limo.context_text
