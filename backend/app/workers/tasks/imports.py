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
    from app.services import batch_service

    # 0) Register the run as a batch (fail-open; None is tolerated everywhere).
    batch_id = None
    async with session_scope() as s:
        imp = await s.get(Import, import_id)
        if imp is None:
            return {"error": "import not found"}
        if imp.batch_id is None:
            batch_id = await batch_service.start(
                "import", imp.workspace_id, project_id=imp.project_id,
                label=imp.filename or imp.source.value, started_by=imp.created_by,
            )
            if batch_id is not None:
                imp.batch_id = batch_id
        else:
            batch_id = imp.batch_id

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
                await batch_service.add_log(batch_id, f"File could not be read: {exc}", level="error")
                await batch_service.finish(batch_id, status="failed", error=str(exc)[:500])
                return {"error": str(exc)}

    # 2) Process staged rows (resumable; commits internally).
    async with session_scope() as s:
        new_ids = await import_service.process(s, import_id)

    # 3) Close the batch from the import's own counters (honest new-vs-existing).
    async with session_scope() as s:
        imp = await s.get(Import, import_id)
        if imp is not None:
            new_n = imp.new_rows if imp.new_rows is not None else len(new_ids)
            updated_n = (
                imp.updated_rows
                if imp.updated_rows is not None
                else max(0, imp.imported_rows - new_n)
            )
            await batch_service.update(
                batch_id,
                totals={
                    "total": imp.total_rows, "done": imp.processed_rows,
                    "ok": imp.imported_rows, "failed": imp.error_rows,
                    "skipped": imp.duplicate_rows,
                },
                counters_inc={"new_links": new_n, "already_there": updated_n},
            )
            await batch_service.add_log(
                batch_id,
                f"Import finished: {new_n} NEW link{'s' if new_n != 1 else ''} added, "
                f"{updated_n} already there (refreshed), {imp.error_rows} failed.",
                data={"import_id": str(imp.id), "new_links": new_n},
            )
            if imp.error_rows:
                await batch_service.add_log(
                    batch_id,
                    f"{imp.error_rows} row(s) could not be imported — open the error report for details.",
                    level="warn",
                )
            qa_note = (
                "Links queued for their first QA check."
                if settings.AUTO_QA_ON_IMPORT
                else "New links are QA pending — start a check from the Backlinks list when ready."
            )
            if new_n:
                await batch_service.add_log(batch_id, qa_note)
            await batch_service.finish(
                batch_id, error=imp.error if imp.status is ImportStatus.FAILED else None
            )

    # 4) Queue the freshly-imported links for their first crawl — only when the
    # workspace explicitly wants automatic QA (manual-by-default per the owners).
    if new_ids and settings.AUTO_QA_ON_IMPORT:
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
