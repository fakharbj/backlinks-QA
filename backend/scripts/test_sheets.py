"""Diagnose Google Sheets connectivity. Run on the server from backend/:

    cd /home/ls_user/htdocs/72.62.81.34.nip.io/backend
    source venv/bin/activate
    python scripts/test_sheets.py

It reads the same .env the app uses and prints, step by step: whether Sheets is
enabled, the service-account email, what it reads from the MAIN sheet (including
the exact URL value per row — this reveals smart-chip cells that hide the URL),
and whether each PROJECT sheet can be opened (reveals sharing problems).
"""

from __future__ import annotations

from app.core.config import settings
from app.integrations import google_sheets


def main() -> None:
    print("== CONFIG ==")
    print("enabled        :", google_sheets.is_enabled())
    print("SA email       :", google_sheets.service_account_email())
    print("main sheet id  :", settings.GOOGLE_MAIN_SHEET_ID)
    print("project col    :", repr(settings.GOOGLE_MAIN_PROJECT_COL))
    print("url col        :", repr(settings.GOOGLE_MAIN_URL_COL))
    print()

    if not google_sheets.is_enabled():
        print(">> Sheets is NOT enabled. Set GOOGLE_SHEETS_ENABLED=true, the service "
              "account (GOOGLE_SA_JSON_FILE or _BASE64), and GOOGLE_MAIN_SHEET_ID in .env.")
        return

    print("== MAIN SHEET ==")
    try:
        rows = google_sheets.read_main_sheet()
    except Exception as exc:  # noqa: BLE001
        print("READ FAILED:", repr(exc))
        print(">> Likely: the main sheet is not shared with the SA email above, or "
              "GOOGLE_MAIN_SHEET_ID is wrong, or the Sheets/Drive API is not enabled.")
        return

    print("rows read      :", len(rows))
    if rows:
        print("headers seen   :", list(rows[0].keys()))
    print()

    for i, row in enumerate(rows, start=1):
        name = row.get(settings.GOOGLE_MAIN_PROJECT_COL, "")
        url = row.get(settings.GOOGLE_MAIN_URL_COL, "")
        sid = google_sheets.extract_spreadsheet_id(url)
        print(f"row {i}: project={name!r}")
        print(f"        url value read = {url!r}")
        print(f"        spreadsheet_id = {sid}")
        if not sid:
            print("        >> No URL found in this cell. If it shows a chip in Sheets, "
                  "the URL is hidden — paste the FULL https://docs.google.com/... as PLAIN TEXT.")
            continue
        try:
            headers, prows = google_sheets.read_project_sheet(sid)
            print(f"        project sheet OK: {len(prows)} rows, headers={headers}")
        except Exception as exc:  # noqa: BLE001
            print(f"        project sheet READ FAILED: {exc!r}")
            print("        >> Share THIS project sheet with the SA email too.")
        print()


if __name__ == "__main__":
    main()
