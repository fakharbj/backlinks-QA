"""Import processing task (parse → stage → process → enqueue crawls)."""

from __future__ import annotations

import uuid

from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.integrations import storage
from app.models.enums import ImportSource, ImportStatus
from app.models.imports import Import
from app.services import import_parse, import_service
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

log = get_logger("worker.imports")


async def _process_async(import_id: uuid.UUID, parse_from_storage: bool) -> dict:
    # 1) Parse + stage (only for file imports; paste/manual are pre-staged).
    if parse_from_storage:
        async with session_scope() as s:
            imp = await s.get(Import, import_id)
            if imp is None:
                return {"error": "import not found"}
            try:
                data = await _download(imp)
                headers, rows = (
                    import_parse.parse_xlsx(data)
                    if imp.source is ImportSource.XLSX
                    else import_parse.parse_csv(data)
                )
                if not imp.column_mapping:
                    imp.column_mapping = import_parse.auto_map(headers)
                await import_service.stage_rows(s, imp, rows)
            except Exception as exc:  # noqa: BLE001
                imp.status = ImportStatus.FAILED
                imp.error = str(exc)[:500]
                log.error("import_parse_failed", import_id=str(import_id), error=repr(exc))
                return {"error": str(exc)}

    # 2) Process staged rows (resumable; commits internally).
    async with session_scope() as s:
        new_ids = await import_service.process(s, import_id)

    # 3) Queue the freshly-imported links for their first crawl.
    if new_ids:
        from app.workers.dispatch import enqueue_backlinks

        enqueue_backlinks(new_ids, priority=False)

    return {"imported": len(new_ids)}


async def _download(imp: Import) -> bytes:
    return await storage.get_bytes_async(settings.S3_BUCKET_IMPORTS, imp.upload_key)


@celery_app.task(
    name="tasks.imports.process_import", bind=True, acks_late=True, max_retries=3,
    autoretry_for=(OperationalError,), retry_backoff=True,
)
def process_import(self, import_id: str, parse_from_storage: bool = False) -> dict:
    return run_async(_process_async(uuid.UUID(import_id), parse_from_storage))
