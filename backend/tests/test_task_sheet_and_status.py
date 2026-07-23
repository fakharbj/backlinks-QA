"""Task-sheet exports + suggestion-count rule + main-sheet Status column.

Owner rules under test:
  * a task's suggestion list = its assigned links + 2 spare picks;
  * the task-sheet export has one row per suggested domain with EMPTY
    Backlink URL / Anchor / Remarks columns beside each row (and pads up to
    the target when the engine has fewer domains);
  * the main sheet's Status cell maps to a project state — blank/typo cells
    never flip anything.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date, timedelta

import pytest

from app.models.enums import ProjectStatus
from app.services.sheet_sync_service import status_from_cell
from app.services.workforce_service import _parse_sheet_date


def test_sheet_date_parser_survives_spreadsheet_rewrites():
    # We export ISO, but Excel re-saves CSV date cells in locale format —
    # the simple sheet's ONLY routing key must survive that round trip.
    iso = date(2026, 7, 23)
    for raw in ("2026-07-23", "2026-07-23 00:00:00", "2026/07/23",
                "7/23/2026", "07/23/2026", "23.07.2026", "23-Jul-2026"):
        assert _parse_sheet_date(raw) == iso, raw
    # Unambiguous day-first (day > 12) parses day-first.
    assert _parse_sheet_date("23/07/2026") == iso
    # Garbage/blank → None, never an exception.
    for raw in ("", "  ", "not a date", "13/13/2026"):
        assert _parse_sheet_date(raw) is None, raw


def test_status_cell_active_variants():
    for raw in ("Active", " active ", "LIVE", "yes", "1", "running", "Active ✓"):
        assert status_from_cell(raw) == ProjectStatus.ACTIVE, raw


def test_status_cell_inactive_variants():
    for raw in ("Inactive", "IN ACTIVE", "in-active", "Paused", "on hold", "0", "closed"):
        assert status_from_cell(raw) == ProjectStatus.PAUSED, raw
    assert status_from_cell("Archived") == ProjectStatus.ARCHIVED


def test_status_cell_blank_or_typo_never_flips():
    # None = leave the project untouched — a typo must never change state.
    for raw in ("", None, "  ", "???", "maybe", "pending review"):
        assert status_from_cell(raw) is None, raw


def test_status_cell_inactive_wins_inside_longer_text():
    # "inactive" contains "active" — the order of checks matters.
    assert status_from_cell("marked inactive by owner") == ProjectStatus.PAUSED


pytestmark_integration = pytest.mark.integration


@pytest.mark.integration
def test_suggestion_count_and_task_sheet_export(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
        reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": email, "password": "Password-12345",
                "full_name": "Sheet QA", "workspace_name": "TaskSheet Ws",
            },
        )
        assert reg.status_code == 201, reg.text
        headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
        proj = client.post("/api/v1/projects", json={"name": "TaskSheet Proj"}, headers=headers)
        project_id = proj.json()["id"]

        day = date.today()
        while day.weekday() == 6:  # skip Sunday (default non-working)
            day += timedelta(days=1)
        label = f"builder-{uuid.uuid4().hex[:6]}"
        a = client.post(
            "/api/v1/workforce/assignments",
            json={
                "project_id": project_id, "user_label": label, "day": day.isoformat(),
                "hours": 2, "link_type_names": ["Profile"], "expected_links": 5,
            },
            headers=headers,
        )
        assert a.status_code == 200, a.text
        assignment_id = a.json()["id"]

        # Count rule: 5-link task → target 7 (items may be fewer; the catalog
        # in a fresh workspace is empty — the TARGET is the contract).
        sugg = client.get(
            f"/api/v1/workforce/assignments/{assignment_id}/domain-suggestions",
            headers=headers,
        )
        assert sugg.status_code == 200, sugg.text
        body = sugg.json()
        assert body["expected_links"] == 5
        assert body["suggestion_target"] == 7
        assert len(body["items"]) <= 7

        # An explicit limit still wins (manager browsing).
        sugg2 = client.get(
            f"/api/v1/workforce/assignments/{assignment_id}/domain-suggestions?limit=3",
            headers=headers,
        )
        assert sugg2.json()["suggestion_target"] == 3

        # Per-task sheet: CLEAN layout — no Task ID / Link # / Priority / Why;
        # a divider row groups the task; one row per suggested domain with the
        # empty fill-in columns.
        exp = client.get(
            f"/api/v1/workforce/task-export?assignment_id={assignment_id}&format=csv",
            headers=headers,
        )
        assert exp.status_code == 200, exp.text
        assert "text/csv" in exp.headers["content-type"]
        rows = list(csv.reader(io.StringIO(exp.content.decode("utf-8-sig"))))
        header = rows[0]
        for col in ("Date", "User", "Project", "Link type", "Suggested domain",
                    "Backlink URL (fill in)", "Anchor text (fill in)", "Remarks (fill in)"):
            assert col in header, col
        for gone in ("Task ID", "Link #", "Priority", "Task note", "Why suggested"):
            assert gone not in header, gone
        user_ix = header.index("User")
        date_ix = header.index("Date")
        fill_ix = header.index("Backlink URL (fill in)")
        proj_ix = header.index("Project")
        lt_ix = header.index("Link type")
        allrows = rows[1:]
        # Data rows carry the user label; divider rows start with "──".
        data = [r for r in allrows if len(r) > user_ix and r[user_ix] == label]
        assert len(data) >= 5
        assert any(r and r[0].startswith("──") for r in allrows)  # task divider present
        assert all(r[fill_ix] == "" for r in data)  # fill-in stays empty

        # Whole-day sheet contains this user's rows.
        exp_day = client.get(
            f"/api/v1/workforce/task-export?day={day.isoformat()}&format=csv",
            headers=headers,
        )
        assert exp_day.status_code == 200, exp_day.text
        assert label in exp_day.content.decode("utf-8-sig")

        # XLSX variant streams a spreadsheet.
        exp_x = client.get(
            f"/api/v1/workforce/task-export?assignment_id={assignment_id}&format=xlsx",
            headers=headers,
        )
        assert exp_x.status_code == 200
        assert exp_x.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument"
        )
        assert exp_x.content[:2] == b"PK"  # zip magic — real xlsx bytes

        # Flat style omits the divider rows.
        exp_flat = client.get(
            f"/api/v1/workforce/task-export?assignment_id={assignment_id}&style=simple&format=csv",
            headers=headers,
        )
        frows = list(csv.reader(io.StringIO(exp_flat.content.decode("utf-8-sig"))))[1:]
        assert not any(r and r[0].startswith("──") for r in frows)

        # ── Round trip: fill two data rows and submit the WHOLE sheet (divider
        # rows have no URL, so they're skipped). Routes by User + Date.
        data[0][fill_ix] = "https://blog.example.com/built-1"
        data[1][fill_ix] = "https://forum.example.org/built-2"
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(header)
        writer.writerows(allrows)
        sub = client.post(
            "/api/v1/workforce/task-import",
            files={"file": ("task-sheet.csv", buf.getvalue().encode("utf-8"), "text/csv")},
            headers=headers,
        )
        assert sub.status_code == 202, sub.text
        out = sub.json()
        assert out["staged"] == 2, out
        assert out["skipped_unknown_task"] == 0
        assert len(out["batches"]) == 1  # one project → one review batch
        batch_id = out["batches"][0]["batch_id"]

        # Isolated link_review batch — nothing imported to the project yet.
        b = client.get(f"/api/v1/batches/{batch_id}", headers=headers)
        assert b.status_code == 200, b.text
        assert b.json().get("kind") == "link_review"
        links = client.get(
            f"/api/v1/backlinks?project_id={project_id}&limit=10", headers=headers
        )
        payload = links.json()
        items = payload["items"] if isinstance(payload, dict) else payload
        assert len(items) == 0  # staged only — approval is the gate

        # Excel-style locale date still routes (Excel rewrites ISO dates).
        us_day = f"{day.month}/{day.day}/{day.year}"
        data[2][fill_ix] = "https://blog.example.io/built-4"
        data[2][date_ix] = us_day
        b2 = io.StringIO()
        w = csv.writer(b2)
        w.writerow(header)
        w.writerow(data[2])
        sub4 = client.post(
            "/api/v1/workforce/task-import",
            files={"file": ("task-sheet.csv", b2.getvalue().encode("utf-8"), "text/csv")},
            headers=headers,
        )
        assert sub4.status_code == 202, sub4.text
        assert sub4.json()["staged"] == 1

        # ── Ambiguity: a second same-day task on a SECOND project.
        proj2 = client.post(
            "/api/v1/projects", json={"name": "TaskSheet Proj B"}, headers=headers
        )
        project2_id = proj2.json()["id"]
        a2 = client.post(
            "/api/v1/workforce/assignments",
            json={
                "project_id": project2_id, "user_label": label, "day": day.isoformat(),
                "hours": 1, "link_type_names": ["Profile & Forums"], "expected_links": 2,
            },
            headers=headers,
        )
        assert a2.status_code == 200, a2.text

        def submit_one(project_cell: str, ltype_cell: str, url: str):
            row = list(data[3])
            row[fill_ix] = url
            row[proj_ix] = project_cell
            row[lt_ix] = ltype_cell
            b3 = io.StringIO()
            w2 = csv.writer(b3)
            w2.writerow(header)
            w2.writerow(row)
            return client.post(
                "/api/v1/workforce/task-import",
                files={"file": ("task-sheet.csv", b3.getvalue().encode("utf-8"), "text/csv")},
                headers=headers,
            )

        # Project blanked, exact link type "Profile" → routes to taskA (proj1).
        sub5 = submit_one("", "Profile", "https://wiki.example.edu/built-5")
        assert sub5.status_code == 202, sub5.text
        assert sub5.json()["batches"][0]["project_id"] == project_id

        # Named project matching nothing → skipped, never guessed.
        sub6 = submit_one("Renamed Project That Does Not Exist", "", "https://news.example.co/b6")
        assert sub6.status_code in (400, 422), sub6.text

        # No project + no link type + two different-project candidates → skipped.
        sub7 = submit_one("", "", "https://misc.example.dev/built-7")
        assert sub7.status_code in (400, 422), sub7.text

        # A sheet with no filled Backlink URL cells is rejected with guidance.
        empty_buf = io.StringIO()
        we = csv.writer(empty_buf)
        we.writerow(header)
        sub2 = client.post(
            "/api/v1/workforce/task-import",
            files={"file": ("task-sheet.csv", empty_buf.getvalue().encode("utf-8"), "text/csv")},
            headers=headers,
        )
        assert sub2.status_code in (400, 422), sub2.text
