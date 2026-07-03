# CLAUDE.md — LinkSentinel working guide

> **This file is auto-loaded every session.** Read **[HANDOFF.md](HANDOFF.md)** once,
> in full, before doing real work — it is the complete source of truth (architecture,
> deployment, env, security, gotchas). This file is the short, always-on operating
> guide: rules, commands, conventions, and pointers.

---

## What this is

**LinkSentinel** — a production backlink-QA + crawling + Google-Sheets-ingest +
ERP-analytics + versioned-reporting platform for an SEO agency.
**Live:** https://72.62.81.34.nip.io/  ·  Stack: FastAPI (async) + Postgres 16 +
Redis + Celery backend; Next.js 14 frontend; PM2 behind CloudPanel nginx on a VPS.

Pipeline: **ingest** (CSV/paste or Google Sheets) → **crawl** source pages (proxy
escalate-on-block) → **QA verdict** (link present? rel? indexed? duplicate? broken?)
→ **alerts/email** on regressions → **analytics** (dynamic filters/facets/pivots) →
**versioned reports** → optional **write-back** to the sheet.

---

## Golden rules (do not violate)

1. **Secrets are env-only.** Never hardcode credentials. Never commit `.env` or
   `service-account.json` (server-only, chmod 600). Add new settings to
   `backend/app/core/config.py` — nothing else reads `os.environ`.
2. **Don't weaken security.** Keep the SSRF guard. Refuse CAPTCHA-solving /
   bot-evasion (this is a defensive QA tool). Tell the user to rotate any key ever
   pasted in chat.
3. **Don't mutate prod data manually.** Prefer a migration or a code path. Direct
   destructive/`UPDATE` SQL on the live DB is gated by the harness and needs the
   user's explicit OK — don't work around it.
4. **Deploy hygiene:** after deploying, `git commit` what you shipped so the repo
   matches the server. Only commit/push when it's the task; branch off `main` if
   asked to push. Co-author trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
5. **Match the surrounding code** — same patterns, naming, comment density (see
   Conventions). This is a long-term, scalable solution; keep changes fully
   connected, relational, dynamic, reliable.
6. **`backend/app.zip` is a stale artifact — ignore it.** Deploy from real files.

---

## Environment & how to run

- **Local repo:** `C:\Users\AR Computer\Desktop\backlinks qa` (Windows). Shell is
  PowerShell; a Bash (Git Bash) tool is also available for POSIX one-liners.
- **Server:** `ssh root@72.62.81.34` (passwordless key already set up).
  Site root: `/home/ls_user/htdocs/72.62.81.34.nip.io/` → `backend/`, `frontend/`,
  `deploy/`, `docs/`. Python venv at **`backend/venv`** (Python 3.13.5).
- **Builds happen on the server** (local `node_modules` may be absent). Don't rely
  on a clean local `npm run build`.

### Deploy (established workflow — tar over SSH, then build/restart)
```bash
# Frontend change:
tar czf - frontend/components frontend/lib | ssh root@72.62.81.34 \
 "tar xzf - -C /home/ls_user/htdocs/72.62.81.34.nip.io && \
  cd /home/ls_user/htdocs/72.62.81.34.nip.io/frontend && npm run build && pm2 restart frontend"

# Backend code (no schema):
tar czf - backend/app | ssh root@72.62.81.34 \
 "tar xzf - -C /home/ls_user/htdocs/72.62.81.34.nip.io && pm2 restart api worker beat"

# Backend + new migration:
tar czf - backend/app backend/alembic | ssh root@72.62.81.34 \
 "tar xzf - -C /home/ls_user/htdocs/72.62.81.34.nip.io && \
  cd /home/ls_user/htdocs/72.62.81.34.nip.io/backend && \
  venv/bin/alembic upgrade head && pm2 restart api worker beat"
```

### Runbook
```bash
pm2 list                                   # api / worker / beat / frontend
pm2 logs api --lines 50 --nostream
pm2 restart all
ssh root@72.62.81.34 "curl -s localhost:8000/healthz; curl -s localhost:8000/readyz"
curl -sk -o /dev/null -w '%{http_code}\n' https://72.62.81.34.nip.io/   # frontend, expect 200
sudo -u postgres psql -d linksentinel      # DB (on the box)
cd backend && venv/bin/pytest -q           # tests (87 pass)
cd backend && venv/bin/alembic upgrade head
```
**Health endpoints (`/healthz` `/readyz` `/metrics`) live at the backend ROOT**, not
under `/api/v1` (nginx only proxies `/api/v1`) — reach them on the box at
`localhost:8000`.

---

## Architecture (one screen)

- **Modular monolith:** one codebase runs as both the FastAPI API (`app.main:app`)
  and the Celery workers. Shared models/services/config.
- **PM2 processes:** `api` (gunicorn+uvicorn :8000) · `worker` (Celery, all queues)
  · `beat` (RedBeat schedule) · `frontend` (Next.js :3000). Defs in
  `deploy/ecosystem.config.js`.
- **Data:** Postgres db `linksentinel` (month-partitioned history, JSONB, native
  enums); Redis = Celery broker/result/RedBeat. Blob storage = local disk
  (`STORAGE_BACKEND=local`, under `backend/var/storage`).
- **Queues:** `crawl.http.0..3`, `crawl.render`, `qa`, `alerts`, `reports`,
  `sheets.sync`, `index.check`, `maintenance`, `default`.

---

## Code conventions (write code that fits)

**Backend**
- **FastAPI + Pydantic v2 + SQLAlchemy 2.0 async** (`Mapped[...]`, `mapped_column`,
  `await db.execute(select(...))`). Alembic for schema (migrations `0001`→`0006`).
- **Layering:** `api/v1/<router>.py` (thin) → `services/<x>_service.py` (logic) →
  `models/` + `schemas/`. Don't put business logic in routers.
- **Config:** import the singleton `from app.core.config import settings`. Add new
  knobs as typed fields in `config.py` (with a comment); never read env elsewhere.
- **Logging:** `from app.core.logging import get_logger` → `log = get_logger("...")`;
  structured (`log.info("event_name", key=value)`), JSON in prod.
- **Network egress lives in `integrations/`** only. Keep verdict/parsing logic as
  **pure functions** so it's unit-testable without the network (see `integrations/
  serp.py`'s `classify_serp_html`). Any ambiguity in index checking →
  `UNCERTAIN`, never a false negative.
- **Analytics is a whitelist:** filters/facets/group-by dimensions are explicit maps
  in `services/analytics_service.py`. Add a dimension there — never interpolate raw
  user input into SQL.
- **Identity/dedup** uses sha256 hash keys (long URLs exceed btree limits).
- **Auth:** access TTL 15 min, refresh 7 days rotating; `POST /auth/refresh`.

**Frontend**
- Entire UI is one tree: `frontend/components/workspace-app.tsx` (search for
  `ReportsDesk`, `AnalyticsDesk`, `Overview`, `Backlinks`, `SheetsDesk`, `TeamDesk`).
- **TanStack Query** for all server state; **`api()` from `frontend/lib/api.ts`** for
  every call. `api()` has a **token manager with auto-refresh on 401** + proactive
  refresh — keep that path intact if you touch it.
- Tailwind + lucide-react. Match the existing component style (small helper
  components: `Metric`, `Status`, `Field`, `Empty`, `Th/Td`).
- **Hooks rule:** call all hooks before any early return (a guard like
  `if (!projectId) return <…/>` must come AFTER `useState`/`useMutation`/`useQuery`).
- The **project selector is a scope switch:** `""` = all-projects (company),
  otherwise a project id. Omit `project_id` from queries when empty; send `null` in
  POST bodies (empty string fails UUID parsing).

---

## Key files

| Need | File |
|---|---|
| Every setting/env, heavily commented | `backend/app/core/config.py` |
| App factory, health/metrics, router mounts | `backend/app/main.py` |
| Reports + versioning logic | `backend/app/services/report_service.py` |
| Dynamic analytics engine | `backend/app/services/analytics_service.py` |
| Sheets ingest + write-back | `backend/app/services/sheet_sync_service.py` |
| Index check orchestration | `backend/app/services/index_service.py` + `integrations/serp.py` |
| Duplicate/identity | `backend/app/services/duplicate_service.py` |
| Proxy egress | `backend/app/integrations/proxy.py` |
| Whole UI | `frontend/components/workspace-app.tsx` |
| API client + token manager | `frontend/lib/api.ts` |
| PM2 process defs | `deploy/ecosystem.config.js` |
| Full handoff / deep dive | `HANDOFF.md` |
| Build plan / phase status | `docs/DEVELOPMENT-PLAN.md`, `docs/FINAL-STATUS.md` |
| Requirements / architecture / runbook | `docs/01-product-requirements.md`, `docs/02-system-architecture.md`, `docs/03-production-runbook.md` |
| Project report (narrative) | `docs/FINAL-YEAR-PROJECT-REPORT.md` |

---

## Gotchas (short list — full list in HANDOFF.md §11)

- **Python 3.13 wheels:** keep `asyncpg>=0.30`, `lxml>=5.3`, `greenlet>=3.1`,
  `pydantic>=2.10` (older pins won't compile). Already fixed in `requirements.txt`.
- **`ModuleNotFoundError: app.workers`** → PM2 `cwd`/venv path wrong; fix the def,
  don't hack `PYTHONPATH`.
- **Google main sheet:** the "Project Sheet URL" cell must be a **plain URL**, not a
  smart chip (API can't read the chip target).
- **serper.dev** is the index-check provider in prod (`SERP_PROVIDER=serper`);
  Google scraping returns a JS-only shell and CSE "search entire web" is deprecated.
- **Reports versioning:** rows created before the version column existed were
  backfilled to `v1/is_latest`; the UI derives version numbers from recency to keep
  the history clean. A stored-data renumber needs user-authorized prod SQL.
- **CRLF warnings** on `git add` (Windows) are harmless.

---

## Current state

Phases 0–8 live + **Phase 9 P0** (`docs/PHASE-9-PLAN.md` is the work queue).
126 tests pass; migrations at `0020`. Phase 9 P0 shipped: unified **batch registry**
(`batches`/`batch_logs`, fail-open `services/batch_service.py`, wired into sheet
sync / imports / rechecks / duplicate scans / re-scores / reports) + **Batches desk**
(live progress, logs, in-app row-error viewer), Sheets-style **multi-select filters**
(comma lists + `(blanks)` sentinel in `backlink_service`), **toast stack**,
**status tooltips** (`STATUS_HELP`), recheck-stale (10/20/30 days),
`metric_check_history` + cached/fresh metric origin. Fixed: report-download 500
(non-ASCII Content-Disposition), duplicate-header sheets breaking sync after
write-back (`_unique_headers`).

**Phase 9 P1+P2 also shipped** (migrations at `0022`): user Performance desk
(project-new vs global-new source domains + previous-period deltas), Overview
Activity trends w/ timeframe compare + weekly chart, Source-Domains project view
(used vs available), competitor opportunity lifecycle (dismiss/re-open survives
recompute, guest-post tag/exclude, CSV export), sync dup_new/dup_previous
counters, **closed signup** (`ALLOW_PUBLIC_REGISTRATION=false`, bootstrap-safe;
tests open it via conftest), and the **workforce module** (`workforce_service` +
`/workforce`): task_assignments as immutable daily snapshots, links-per-hour
productivity (global + user override; seeded 5/hr, Profile 30/hr — owners must
correct), working-days calendar (Mon–Sat default), leave approve/reject →
excusals in plan-vs-done. Tasks & Calendar desk in both navs.

**Phase 9 finalization also shipped** (migrations at `0023`): TeamLead member
scoping (`teamlead_users` + Team-desk card; scoped managers only see their
people in Performance/Tasks/Leave), admin **Reset password** (one-time temp
password, audited), and the **in-app report viewer** (`GET /reports/{id}/rows`
parses stored CSV/XLSX; View button + paginated table in ReportsDesk).

**Later increments** (migrations at `0025`, 127 tests): UX elevation (GSC-style
`TrendChart`, analytics multi-select filters, drill-downs via `openBacklinks`
f_* deep-link params, exports everywhere), modern project picker + distinct
global/project dashboards, admin deletes everywhere (links/projects/reports/
runs/competitor uploads/alert rules; typed-name confirm + audit), scale pass
(`0025` composite indexes, keyset/sargable queries, 30s Redis micro-cache on
dashboard trends, chunked rescore). **Sheets-sync UX** (no new migration):
realtime sync progress in SheetsDesk (polls `/batches?kind=sheet_sync`, live
per-sheet progress row, completion toast), honest new-vs-refreshed accounting
(per-tab logs "X NEW, Y already there (refreshed)" + sample new URLs +
`new_links`/`already_there` counters), manual column mapping per sheet
(`GET/PUT /sheets/{id}/mapping`, live headers, auto vs manual, audited PUT),
configurable write-back columns (`sheet_sources.writeback_columns`).

**Remaining (optional/P3):** task-sheet 2-way sync (flagged off), SMTP-based
self-serve password reset, shared saved views. Demo rows from verification:
assignment (alex · Jul 2 · Limo Black) + approved leave (alex Jul 10–11) —
removable in the Tasks desk. Temp account `qa-ui-test@linksentinel.local`
(creds `/tmp/ls_qa_creds.txt`) — deactivate/remove when owners confirm. Open
questions PHASE-9-PLAN §15 (Q1 "QA" metric, Q2 real productivity numbers).
