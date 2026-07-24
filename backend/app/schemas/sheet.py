"""Google Sheets schemas (Phase 2)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class SheetSourceOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    # The linked project's lifecycle status (active/paused/archived) — inactive
    # projects are excluded from bulk/auto sync and marked in the UI.
    project_status: str | None = None
    spreadsheet_id: str
    sheet_tab: str | None
    source_url: str | None
    last_synced_at: datetime | None
    last_sync_status: str | None
    last_sync_error: str | None
    row_count: int
    imported_count: int
    updated_count: int
    writeback_enabled: bool
    # Pending Project-Sheet-URL change parked for admin confirmation (the main
    # sheet now points this project at a different spreadsheet). Null = none.
    pending_spreadsheet_id: str | None = None
    pending_source_url: str | None = None
    url_change_detected_at: datetime | None = None


class SheetTabOut(BaseModel):
    id: uuid.UUID
    gid: str
    tab_name: str
    link_type_name: str | None = None
    import_enabled: bool
    qa_enabled: bool
    status: str
    row_count: int


class SheetTabUpdate(BaseModel):
    link_type_name: str | None = None
    import_enabled: bool | None = None
    qa_enabled: bool | None = None


class SheetsApiLimitIn(BaseModel):
    # Max Google Sheets API READ requests per minute we allow ourselves. Google's
    # per-project cap is ~300/min; keep this at or below it. 0 disables throttling.
    reads_per_min: int = Field(ge=0, le=300)


class SheetsApiLimitOut(BaseModel):
    reads_per_min: int
    default: int
    max: int = 300


class SheetConfigOut(BaseModel):
    enabled: bool
    service_account_email: str | None
    main_sheet_id: str | None


class SheetSyncResponse(BaseModel):
    message: str
