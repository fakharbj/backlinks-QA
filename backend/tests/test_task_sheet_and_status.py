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

        # Per-task sheet: CSV with the fill-in columns, padded to ≥5 rows so
        # every link the person must build has a line.
        exp = client.get(
            f"/api/v1/workforce/task-export?assignment_id={assignment_id}&format=csv",
            headers=headers,
        )
        assert exp.status_code == 200, exp.text
        assert "text/csv" in exp.headers["content-type"]
        rows = list(csv.reader(io.StringIO(exp.content.decode("utf-8-sig"))))
        header = rows[0]
        assert "Backlink URL (fill in)" in header
        assert "Anchor text (fill in)" in header
        assert "Suggested domain" in header
        data = rows[1:]
        assert len(data) >= 5
        id_col = header.index("Task ID")
        fill_col = header.index("Backlink URL (fill in)")
        assert all(r[id_col] == assignment_id for r in data)
        assert all(r[fill_col] == "" for r in data)  # fill-in stays empty

        # Whole-day sheet contains the same task.
        exp_day = client.get(
            f"/api/v1/workforce/task-export?day={day.isoformat()}&format=csv",
            headers=headers,
        )
        assert exp_day.status_code == 200, exp_day.text
        assert assignment_id in exp_day.content.decode("utf-8-sig")

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

        # ── Round trip: fill two Backlink URL cells and submit the sheet back.
        for i, url in enumerate(
            ("https://blog.example.com/built-1", "https://forum.example.org/built-2")
        ):
            data[i][fill_col] = url
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(header)
        writer.writerows(data)
        sub = client.post(
            "/api/v1/workforce/task-import",
            files={"file": ("task-sheet.csv", buf.getvalue().encode("utf-8"), "text/csv")},
            headers=headers,
        )
        assert sub.status_code == 202, sub.text
        out = sub.json()
        assert out["staged"] == 2
        assert out["skipped_unknown_task"] == 0
        assert len(out["batches"]) == 1  # one project → one review batch
        batch_id = out["batches"][0]["batch_id"]

        # The batch is an isolated link_review batch — nothing imported yet.
        b = client.get(f"/api/v1/batches/{batch_id}", headers=headers)
        assert b.status_code == 200, b.text
        binfo = b.json()
        assert binfo.get("kind") == "link_review"
        links = client.get(
            f"/api/v1/backlinks?project_id={project_id}&limit=10", headers=headers
        )
        assert links.status_code == 200
        payload = links.json()
        items = payload["items"] if isinstance(payload, dict) else payload
        assert len(items) == 0  # staged only — approval is the gate

        # ── Simple style: main columns only — no Task ID / plumbing columns.
        exp_s = client.get(
            f"/api/v1/workforce/task-export?day={day.isoformat()}&style=simple&format=csv",
            headers=headers,
        )
        assert exp_s.status_code == 200, exp_s.text
        s_rows = list(csv.reader(io.StringIO(exp_s.content.decode("utf-8-sig"))))
        s_header = s_rows[0]
        assert "Task ID" not in s_header
        assert "Priority" not in s_header
        assert "Why suggested" not in s_header
        for col in ("Date", "User", "Project", "Link type", "Suggested domain",
                    "Backlink URL (fill in)"):
            assert col in s_header, col
        s_data = s_rows[1:]
        assert len(s_data) >= 5  # still padded to the task's target
        assert "simple" in exp_s.headers["content-disposition"]

        # Simple sheet round trip: no Task ID column → rows route by
        # User + Date (narrowed by Project / Link type).
        s_fill = s_header.index("Backlink URL (fill in)")
        s_data[0][s_fill] = "https://directory.example.net/built-3"
        s_buf = io.StringIO()
        w3 = csv.writer(s_buf)
        w3.writerow(s_header)
        w3.writerows(s_data)
        sub3 = client.post(
            "/api/v1/workforce/task-import",
            files={"file": ("task-sheet_simple.csv", s_buf.getvalue().encode("utf-8"), "text/csv")},
            headers=headers,
        )
        assert sub3.status_code == 202, sub3.text
        out3 = sub3.json()
        assert out3["staged"] == 1
        assert out3["skipped_unknown_task"] == 0

        # Excel-style locale dates in the simple sheet still route (the Date
        # column is the simple sheet's only key and Excel rewrites it).
        date_ix = s_header.index("Date")
        us_day = f"{day.month}/{day.day}/{day.year}"
        s_data[1][s_fill] = "https://blog.example.io/built-4"
        s_data[1][date_ix] = us_day
        s_buf2 = io.StringIO()
        w4 = csv.writer(s_buf2)
        w4.writerow(s_header)
        w4.writerow(s_data[1])
        sub4 = client.post(
            "/api/v1/workforce/task-import",
            files={"file": ("task-sheet_simple.csv", s_buf2.getvalue().encode("utf-8"), "text/csv")},
            headers=headers,
        )
        assert sub4.status_code == 202, sub4.text
        assert sub4.json()["staged"] == 1

        # ── Ambiguity handling. Assignments are unique per (project, user,
        # day), so a second same-day task must live on a SECOND project:
        # taskA = proj1 ["Profile"], taskB = proj2 ["Profile & Forums"].
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
            row = list(s_data[2])
            row[s_fill] = url
            row[s_header.index("Project")] = project_cell
            row[s_header.index("Link type")] = ltype_cell
            buf2 = io.StringIO()
            w = csv.writer(buf2)
            w.writerow(s_header)
            w.writerow(row)
            return client.post(
                "/api/v1/workforce/task-import",
                files={"file": ("task-sheet_simple.csv", buf2.getvalue().encode("utf-8"), "text/csv")},
                headers=headers,
            )

        # Substring types must NOT cross-match: with the Project cell blanked
        # (edited sheet), "Profile" must route to taskA by EXACT type — not be
        # conflated with "Profile & Forums" and min()-routed by UUID.
        sub5 = submit_one("", "Profile", "https://wiki.example.edu/built-5")
        assert sub5.status_code == 202, sub5.text
        assert sub5.json()["staged"] == 1
        assert sub5.json()["batches"][0]["project_id"] == project_id  # taskA's project

        # A row naming a project that matches no candidate is SKIPPED, never
        # guessed into another project (rename-after-export safety).
        sub6 = submit_one(
            "Renamed Project That Does Not Exist", "", "https://news.example.co/built-6"
        )
        assert sub6.status_code in (400, 422), sub6.text  # nothing routable

        # No project + no link type + two candidates on different projects →
        # ambiguous, skipped (never misattributed).
        sub7 = submit_one("", "", "https://misc.example.dev/built-7")
        assert sub7.status_code in (400, 422), sub7.text

        # A sheet with no filled Backlink URL cells is rejected with guidance.
        empty_buf = io.StringIO()
        w2 = csv.writer(empty_buf)
        w2.writerow(header)
        sub2 = client.post(
            "/api/v1/workforce/task-import",
            files={"file": ("task-sheet.csv", empty_buf.getvalue().encode("utf-8"), "text/csv")},
            headers=headers,
        )
        assert sub2.status_code in (400, 422), sub2.text
