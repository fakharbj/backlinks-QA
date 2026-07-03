"""Google Sheets client (service-account auth).

Reads the global main sheet (Project Name + Project Sheet URL) and each project
sheet's rows. Synchronous (gspread) — callers run it via ``asyncio.to_thread``.
Credentials come from env only: a base64 service-account JSON, or a path to it.
Share each sheet with the service-account email for access.
"""

from __future__ import annotations

import base64
import json
import os
import re

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("integrations.google_sheets")

_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9\-_]+)")


def is_enabled() -> bool:
    return bool(
        settings.GOOGLE_SHEETS_ENABLED
        and _service_account_info() is not None
        and settings.GOOGLE_MAIN_SHEET_ID
    )


def service_account_email() -> str | None:
    info = _service_account_info()
    return info.get("client_email") if info else None


def _service_account_info() -> dict | None:
    if settings.GOOGLE_SA_JSON_BASE64:
        try:
            return json.loads(base64.b64decode(settings.GOOGLE_SA_JSON_BASE64))
        except Exception as exc:  # noqa: BLE001
            log.error("google_sa_base64_invalid", error=repr(exc))
            return None
    path = settings.GOOGLE_SA_JSON_FILE
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:  # noqa: BLE001
            log.error("google_sa_file_invalid", path=path, error=repr(exc))
            return None
    return None


def _client():
    import gspread  # imported lazily so the dependency is optional

    info = _service_account_info()
    if info is None:
        raise RuntimeError("Google service-account credentials are not configured")
    return gspread.service_account_from_dict(info)


def extract_spreadsheet_id(url_or_id: str) -> str | None:
    """Return the spreadsheet ID from a full Sheets URL or a bare ID."""
    if not url_or_id:
        return None
    value = url_or_id.strip()
    match = _SHEET_ID_RE.search(value)
    if match:
        return match.group(1)
    # Looks like a bare ID already (no slashes/spaces).
    if "/" not in value and " " not in value and len(value) > 20:
        return value
    return None


def _open_worksheet(client, spreadsheet_id: str, tab: str | None):
    sheet = client.open_by_key(spreadsheet_id)
    if tab:
        return sheet.worksheet(tab)
    return sheet.sheet1


def list_worksheets(spreadsheet_id: str) -> list[dict]:
    """Return every tab in a spreadsheet: ``[{title, gid, index}]`` (stable gid)."""
    client = _client()
    sheet = client.open_by_key(spreadsheet_id)
    return [
        {"title": ws.title, "gid": str(ws.id), "index": ws.index}
        for ws in sheet.worksheets()
    ]


def read_main_sheet() -> list[dict[str, str]]:
    """Rows of the global main sheet as dicts keyed by header."""
    client = _client()
    ws = _open_worksheet(client, settings.GOOGLE_MAIN_SHEET_ID, settings.GOOGLE_MAIN_SHEET_TAB)
    return [
        {str(k): ("" if v is None else str(v)) for k, v in r.items()}
        for r in ws.get_all_records()
    ]


def _unique_headers(raw: list) -> list[str]:
    """Normalise a header row: blanks become ``column_N`` and duplicates get a
    ``_2``/``_3`` suffix. Write-back adds result columns to live sheets, after
    which ``get_all_records`` refuses the sheet ("header row ... not unique") —
    so we read raw values ourselves and keep syncing regardless of header state."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for i, cell in enumerate(raw):
        name = str(cell).strip() or f"column_{i + 1}"
        n = seen.get(name, 0)
        seen[name] = n + 1
        out.append(name if n == 0 else f"{name}_{n + 1}")
    return out


def read_project_sheet(
    spreadsheet_id: str, tab: str | None = None
) -> tuple[list[str], list[dict[str, str]]]:
    """Return (headers, rows) for a project sheet; rows are dicts keyed by header.
    Tolerates duplicate/blank header cells (common after write-back)."""
    client = _client()
    ws = _open_worksheet(client, spreadsheet_id, tab)
    values = ws.get_all_values()
    if not values:
        return [], []
    headers = _unique_headers(values[0])
    rows: list[dict[str, str]] = []
    for raw_row in values[1:]:
        if not any(str(c).strip() for c in raw_row):
            continue  # skip fully blank rows
        rows.append(
            {
                headers[i]: ("" if i >= len(raw_row) or raw_row[i] is None else str(raw_row[i]))
                for i in range(len(headers))
            }
        )
    return headers, rows


def _col_letter(n: int) -> str:
    """1 → A, 2 → B, … 27 → AA (1-based column index to A1 letter)."""
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def write_back(
    spreadsheet_id: str, tab: str | None, result_headers: list[str], values_by_row: dict[int, list]
) -> dict:
    """Write RESULT columns into a project sheet without touching the input columns.

    Results go into a fresh column block starting one gap-column to the right of the
    existing data, so manual/input columns are never overwritten. ``values_by_row``
    is keyed by the actual sheet row number (header = row 1).
    """
    client = _client()
    ws = _open_worksheet(client, spreadsheet_id, tab)
    input_cols = len(ws.row_values(1)) or 1
    start_col = input_cols + 2  # leave one empty gap column
    ncols = len(result_headers)
    max_row = max([1, *values_by_row.keys()])

    block: list[list] = [list(result_headers)]
    for r in range(2, max_row + 1):
        vals = values_by_row.get(r)
        block.append(
            [("" if v is None else str(v)) for v in (vals if vals is not None else [""] * ncols)]
        )

    rng = f"{_col_letter(start_col)}1:{_col_letter(start_col + ncols - 1)}{max_row}"
    ws.batch_update([{"range": rng, "values": block}])
    return {"rows": max_row - 1, "range": rng}
