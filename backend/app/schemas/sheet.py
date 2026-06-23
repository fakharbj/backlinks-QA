"""Google Sheets schemas (Phase 2)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class SheetSourceOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
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


class SheetConfigOut(BaseModel):
    enabled: bool
    service_account_email: str | None
    main_sheet_id: str | None


class SheetSyncResponse(BaseModel):
    message: str
