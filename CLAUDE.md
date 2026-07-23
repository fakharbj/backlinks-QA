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
- **Render pool is LIVE** (since 2026-07-05): `RENDER_ENABLED=true` on the server,
  Playwright chromium installed in `backend/venv` (`playwright install chromium`).
  JS-only pages (Notion/SPAs) render in the worker; pages that still can-not be
  read classify as “Needs review — JavaScript page”, never “link missing”.
  Chromium cannot use the authenticated IPRoyal proxy (ERR_PROXY_AUTH_UNSUPPORTED)
  — renders go direct by design.

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

**Brief-perfection pass also shipped** (no new migration, 128 tests): sheet
sync **auto-creates users** (`SHEETS_AUTO_CREATE_USERS`, Viewer + project-scoped,
case-insensitive label matching, links unlinked catalog mappings, attributes
rows; import resolves the User column via the catalog), Performance custom date
range + custom compare window (`compare_from/to`) + user-vs-user side-by-side,
Tasks **Schedule grid** (users×days) + per-user productivity override UI
(`DELETE /workforce/productivity`), Team per-member **Projects** scoping column
(`GET/PUT /team/members/{id}/projects`).

**Final production-hardening pass shipped** (migration `0026`, 133 tests):
Loop1 full-width shell + thin header + compact tables + one-line dates +
plain-English statuses (PASS→Qualified, FAIL→Not qualified, PENDING→QA pending)
+ `linkTypeLabel` display names + clickable Analytics cards + inline drill +
`SortTh`/`sortRows` sortable-header standard + password-manager-friendly login.
Loop2 **manual QA by default** (`AUTO_QA_ON_IMPORT=false`; imports/syncs leave
links "QA pending"), scoped check actions w/ confirmations (pending/filtered/
stale/selected; "Recheck everything" removed), file-import upsert (no dup
re-imports; `imports.new_rows/updated_rows`), sheet row-drift repoint+QA-reset,
target filter, `targets_on_source` chip, Link date vs import date, server-side
header sorting + Load more (keyset asc/desc). Loop3 competitor URL required
(name optional→domain), per-upload new/seen-before diff (counts bug fixed),
SEMrush header parsing + preview + template, GP guest-post variants, domain
grid search/sort/PA/expand/load-more. Loop4 reports list-first (builder behind
button), search/type filter, inline viewer under card, 3s generating poll.
Loop5 editable **week planner** (users×Mon-Sun, +Add/edit/× in cells, leave +
non-working overlays), by-project view, priority/note/manual-target,
`rate_source`/`lph_used` snapshots, over-allocation/leave/non-working warnings,
`/workforce/labels`. Loop6 role-safe nav via `/auth/me` (viewer→**My Work**
only desk: today/week/targets/completion/self-leave), viewer data scoping
(day-report/leaves/performance/productivity self-only; `/employees` manager+),
self-only leave requests, deactivation message ("account is inactive").

**Final batch 4 shipped + deployed** (no new migration, 149 tests): product
renamed **"Performance by Techsa"** (TopBar/login/page metadata; login shows
the company logo + "Powered by Techsa" footer). Public `GET /auth/branding`
is **primary-workspace-scoped** (oldest active workspace — test workspaces
can never hijack the login branding). Settings → **Company & branding** card
(name/domain/logo ≤300KB data-URI; `company_domain` rebrands sheet
auto-provisioned emails, with legacy-address reuse so changing it never
duplicates accounts) + per-project logos (`project_logos` setting, shown in
the project picker). Nav reorg: Monitor = Dashboard/Analytics/Performance,
"All projects"→"Dashboard", **Employees merged into Team** (pill tabs),
project nav gains project-scoped Sheets. Backlinks toolbar: **Run QA check /
Check indexing / Check DA·PA·AS** (three separate actions); `MetricTag`
0-100 color tags everywhere (grid Metrics column, drawer Authority row,
source-domains + competitor desks); Source Domains split buttons **Check
DA/PA (Moz)** / **Check AS (Semrush)** via `fetch-metrics?providers=`;
`BacklinkRow` carries `domain_da/domain_pa/domain_as` (bounded per-page
lookup, keyset path untouched). Competitor: links enriched w/ DA/PA/AS +
Opportunity/Already have/Dismissed tags; summary `avg_da/avg_as` cards.
Tasks: **standing weekly plans** (`PUT/DELETE /workforce/templates/entry`
upserts one person×weekday×project cell and materializes this + next week;
"Repeat every week" checkbox in the assign form), assign form moved beside
the planner, month calendar got Mon–Sun headers + first-day offset, chips
show `@lph/h` rate, user dashboard productivity card w/ inline personal-rate
editor. Project create: **target domain compulsory** + instant-feedback cache
seeding. Perf: argon2 moved off the event loop (`asyncio.to_thread` +
`_DUMMY_HASH`) — concurrent logins no longer stall requests (the reported
"5s project create"). NOTE: Semrush AS stays "—" until
`SEMRUSH_RAPIDAPI_ENDPOINT` is set in prod `.env` (Moz DA/PA already live
via `RAPIDAPI_KEY`).

**Batch System shipped + deployed** (migration `0029`, 152 tests): manual
imports are now **staged, never direct**. `POST /imports/paste|file` creates a
`link_review` batch (`batch_items`: presence new/existing/duplicate vs the
project + in-batch, state pending→checking→checked|failed→approved|rejected);
QA runs ISOLATED on the worker (`tasks.staging.check_staged_links`, full
engine: proxy escalation + render pool + markdown/redirect matching) with
verdicts stored in `item.payload.qa` only — `backlink_records`/`crawl_results`
untouched until **Approve**, which feeds approved rows through the normal
`import_service` pipeline linked to the same batch (logs + row errors in one
place). **Import Source Domains** (global Ingest nav + Source Domains button):
paste domains → `domain_import` batch → inline metric checks (Moz DA/PA/Spam,
Semrush AS, RDAP age; capped `BATCH_DOMAIN_CHECK_CAP`/call) → approve into
`source_domains` with **`origin='imported'`** (recompute's orphan-sweep only
deletes `origin='derived'` — imported catalog rows survive with 0 backlinks).
Batches got human ids **`#B-<seq>`** (global sequence, backfilled
chronologically), status **"review"**, `review_pending` counts, and a full
**Batch Details page** (summary cards that set filters, state/presence chip
filters + search, bulk select, Run QA / Check DA/PA / Check AS / Approve /
Reject / Re-run failed, per-item expandable QA/metrics facts, clean logs +
row-error viewer) — same UX global + project. `parse_paste` is now
header-aware (a recognized header line switches to full CSV parsing — extra
columns like anchor/campaign are kept, not dropped). ImportDesk stages + file
upload; new DomainImportDesk; `f_batch` deep-link opens a batch cross-desk.
Kind/status wording maps (`BATCH_KIND_LABEL`/`BATCH_STATUS`). Live-verified
end-to-end on prod (staged link → worker verdict PASS/94 → 0 rows in project
→ batch deleted). Sheet sync intentionally still writes direct (automated
pipeline; unchanged).

**Final delivery phase shipped + deployed** (no new migration, 155 tests):
five delivery-gate features. (1) **Imports work global + project**: the Imports
desk now has a project picker in the global (no-project) view (links still
always belong to a project); in project scope the **target URL is optional** —
rows pasted as bare source URLs inherit the project's target
(`target_urls[0]` else `https://<target_domain>`), applied in
`batch_review_service.stage_link_import(default_target=…)` and echoed as
`default_target` in the staged response. (2) **Competitor parent grouping**:
uploads group under a **parent competitor** keyed by the registrable domain of
`competitor_url` (`competitor_service.competitor_key`); `GET /competitors/parents`
(one row per competitor: display_name — the non-domain name wins, else the
domain — uploads/total_rows/new_domains/last_upload_at/sheet_ids) +
`GET /competitors/parents/backlinks?competitor=&q=` (all source URLs across the
competitor's uploads, enriched w/ DA/PA/AS + opportunity decision + `upload_name`,
searchable). CompetitorDesk's flat Uploads list → a **Competitors** list:
expand a competitor to see its uploads (each still deletable) + a searchable
per-competitor source-URL panel. (3) **User Dashboards is its own desk**
(`users` tab in Monitor, global + project nav): a person picker + people-card
grid; picking someone opens the full `UserDashboard`, now organized into
**Overview / Projects / Plans & calendar / Rates & leave** tabs. Performance is
decoupled — its person table deep-links into the Users desk via `openUserDash`
(`f_user` param); `dashUser` removed from PerformanceDesk. (4) **Nav reorg**:
Monitor group leads (Dashboard/Analytics/Performance/User Dashboards); project
nav puts Monitor above Ingest. (5) **Analytics shows the actual links**: a
**Matching links** card lists the backlinks behind the current analytics
filters (clickable rows → the shared `BacklinkDetailDrawer`, reused verbatim
from the Backlinks desk), an "Open in Backlinks" jump, and the inline drill
rows also open the drawer. Live-verified on prod (bare-URL paste → target
defaulted; two uploads → one parent "Rival Smoke Inc"). Deployed, built, PM2
restarted, site 200; DB untouched.

**Sheet-mapping finalization shipped + deployed** (migration `0030`, 158
tests): the Google-Sheets column mapping is now flexible + preview-driven for
real production sheets. Migration `0030` adds per-tab `column_mapping`,
`field_constants`, `header_row`, `headers_snapshot` to `google_sheet_project_tabs`
(all nullable → existing source-level mappings still work as the fallback).
`GET /sheets/{id}/mapping?tab_id=` now returns a **live preview** (real headers
+ up to 8 sample rows read at the tab's header row), the effective mapping
(per-tab → source default → auto), `auto_map_report` match counts, per-tab
constants, `header_row`, `field_meta` (labels/required/help/group from
`import_parse.CANONICAL_FIELD_META`), and `project_target`. `PUT` takes
`apply_to: tab|source|all_tabs`. Sync resolves mapping per tab, reads at
`tab.header_row`, applies `field_constants` (fill-when-absent) + **target
default from the project** (unifies with imports) via new
`stage_rows(field_constants=, default_target=)` kwargs; `read_project_sheet`
gained a `header_row` param (default 1 = unchanged). The **redesigned
SheetMappingEditor**: tab switcher, auto scorecard + reset, header-row input,
required/coverage panel (Source URL hard-required → Save blocked; Target URL
shows "defaults to <project target>"), a live preview table with the mapping
dropdown above each real column of data, constant-value chips, write-back
column picker, and three save scopes. Deployed; DB data untouched (additive
columns only). NOTE (pre-existing, out of scope): sheet write-back still
assumes headers on row 1.

**Enterprise Polish phase shipped + deployed** (migrations `0031`→`0036`, 208
tests) — 13 brief areas as Tranches A–I, each committed + prod-deployed:
**A** all date types across the pipeline (`0031`). **B** spam transparency +
scoring-engine fixes. **C** Source Domains enterprise + Rules Engine + server
exports (`0033`). **D** Analytics/Dashboard KPI boxes + connected filters.
**E** Duplicate management — side-by-side compare, similarity, filters, bulk +
**durable audit** (`0034`,`0035`: `backlink_conflict_actions` has NO FK so the
log outlives a collapsed group; `list_actions`/endpoint workspace-scoped, never
`get_detail`). **F** User Dashboard redesign — full KPI vocabulary, team
benchmark, `date_type` (created/checked/sheet), per-link-type bars,
sortable/exportable projects. **G** Batch **delete-with-rollback**
(`batch_rollback_service`: reverts rows a batch CREATED via
`backlink_records.import_id` — set on INSERT only, so refreshed rows are kept;
domain batches revert catalog-only imported rows; approve/revert serialize on a
pg advisory lock `batch:<id>`; revert refused while `status='running'`; conflict
groups re-detected after revert) + **QA execution settings** (`qa_settings_service`,
`qa_execution` Setting KV → `dataclasses.replace(CrawlConfig…)` in the staged
worker; `GET/PUT /qa-settings`) + real-time/never-empty logs. **H** **Gmail
tracking** (`0036`: `gmail_accounts`+`gmail_assignments`, assignment-history
layer, NO OAuth; `/gmail` router; Team-desk "Gmail accounts" tab). **I**
**exports-everywhere** (`GET /backlinks/export` streams the FULL filtered set,
CSV/XLSX, keyset-paged, 50k cap — fixes the old 200-row cap; competitor CSV uses
shared `downloadCsv`) + **spam consistency** (`domain_spam` via the per-page
`source_domains` lookup → shared `SpamTag` in Backlinks grid/drawer + competitor
grid). NOTE: DA/PA/AS/Spam show "—" until a metrics check runs
(`RAPIDAPI_KEY`/`SEMRUSH_RAPIDAPI_ENDPOINT`).

**Delivery-polish batch shipped + deployed** (2026-07-22, migrations `0053`–
`0055`, 239 tests, docs/DELIVERY-POLISH-PLAN.md): **T1** 8 UX fixes (viewer
nav minus Plans&calendar, combined "New source domains" card, dropdown-clip
fix, This-week-first + week nav, By-project View-all, planner edit MODAL,
Needs-review=PLUM (.pill-review), filter type-ahead via FilterMultiSelect
onSearch — facets are top-50 only). **T6 scoring**: global rule-set v2 zeroes
anchor-changed/canonical-missing/all link-placements (0053); PQ-06 →
_UNSCORED_CODES; classification is SCORE-ONLY past hard gates (≥80 = PASS even
w/ sponsored −10); staging passes the ruleset; retro-rescored 44,278 links
(WARNING→PASS 1,907; final PASS 14,575/WARN 9,899). **T3 batches**: children
carry meta.parent_batch_id (0054 backfill), /batches hides children
(top_level default; ?parent= lists a run's children), details page links
parent↔children, Load more; stale bulk parents self-heal after 3h
(_heal_stale_parents in auto_sync_tick — worker restarts mid-run used to
strand them). **T4 competitors**: ?competitor= on /domains; domains grid
hidden behind "Show →", per-competitor domains inline in the expanded row.
**T2**: weekly overbooked/free/utilization ignore company non-working days
(Saturday stays working — owner rule: only manually-off calendar days count);
self-service My settings (avatar ≤300KB users.avatar_data_uri 0055 via
PUT /auth/avatar; POST /auth/change-password keeps sessions). **T5 team**:
members table → ⋯ actions menu + real modals (edit login, one-time temp
password w/ copy) + avatars in rows.

**Final-changes program shipped + deployed** (2026-07-22 #2, migrations
`0057`, 254 tests, docs/FINAL-CHANGES-PLAN.md, tranches F1–F6): **F1** viewer
rules (no exports on selfView, 30-day default), My Work Target-vs-done paired
bars, myopps explainer, User Dashboards white-label (active-only + "Show all",
list⇄grid, avatars, no employment wording) + global `show_avatars` display
pref (branding Setting → /auth/me prefs, useShowAvatars), Backlinks filters
container + scoring-guide info icon. **F2** Tasks & Calendar sidebar
sub-pages (planner/by-user/by-project/working-days/leave; TASKS_SECTIONS
pattern), Productivity moved to Settings ProductivityCard (incl. per-person
overrides), leave form w/ person picker + reason, **completion clock**
`TASK_COMPLETION_START_DATE=2026-07-27` (5 SQL :pf clamps in
performance_service + day_report pre-cutoff excusal). **F3** "Why this run had
problems" batch panel + list reason hints + warn-level normalization; Team
page header/tab bar + invite modal. **F4** IP-bound sessions
(`bind_sessions` → revoke on refresh IP change; rotated tokens carry ip/ua),
ip rule remarks (`ip_notes`, "ip | note" lines) + `team_overrides`
(user>team>role>master), Security activity log (GET /settings/security-log;
logout + credential-failure audits now carry real IP/device). **F5** intern
role (0057): stage+check only, own-batches-only visibility, approve/reject =
QA+ (`_require_reviewer` — the keep/partial/full transfer gate), INTERN_NAV,
promotion = role change. **F6** My Work suggestion manager (status pages,
search/filters/sort, bulk use/dismiss, similar-type drill, CSV+TXT only).

**System-improvement program G1–G3 shipped + deployed** (2026-07-23, no new
migration, 257 tests): **G1 security** — per-request IP enforcement in
`get_auth_context` (cached rules 20s TTL + `rules_can_enforce` short-circuit +
fail-open; `kill_sessions` revokes via its own session_scope, audit-throttled
5min) so changing IP off an approved network ends the session on the very next
request; blocked-IP list (wins over allow) w/ remarks; `GET
/settings/login-ips/effective` rule tester (which layer decides: user > team >
role > master) + tester UI in LoginIpCard; refresh-path full re-check. **G2**
— competitor expanded-view fix (`cbc.competitor_sheet_id` typo → SQL error →
silent empty panel; + error/retry/empty states), `AvatarBubble` +
`useLabelAvatars` avatars everywhere (TopBar profile, login, UserDashboard
hero, team benchmark, leave rows, completion-by-user, Team rows/grid — all
honoring branding `show_avatars`), dual light/dark workspace logos
(`logo_dark_data_uri`, CSS `dark:` swap + cross-fallback, BrandingCard two
upload cards), load-more sweep (Team members 25, leaves 30, User Dashboards
36 w/ "Showing X of Y"). **G3** — `/interns` router (manager+): per-intern
live analytics from review batches (items/approved/rejected/open/failed/
QA-pass/avg score/rates) + reviewer feedback + ready-to-promote flag (Setting
`intern_reviews`, append-only notes, audited); **InternsDesk** (WORKSPACE_NAV
"interns"): KPI row, active/inactive filter, expandable intern rows → stat
cards, submissions list (Review → opens batch), feedback history + composer,
Mark-ready toggle, admin Promote (role change; data transfer stays the
approve pipeline). **Team page v2**: members toolbar (search, role filter,
active-only default + Show all, sort name/role/last-sign-in, list⇄grid w/
member cards, persisted prefs) + **Team settings hub** tab (live avatar
toggle writing branding + where-it-lives descriptions for IP rules/security
log/working days/rates/roles/scoping/branding).

**Task-sheet + main-sheet-status batch shipped + deployed** (2026-07-23 #2, no
new migration, 262 tests): (1) **suggestion count = assigned links + 2**
(`suggest_for_task(limit=None)` → `expected_links + 2`, clamped ≤50; response
carries `expected_links`/`suggestion_target`; widget dropped its `limit=8` and
shows an "N links + 2 spare" chip). (2) **Task-sheet exports** — `GET
/workforce/task-export?assignment_id=|day=&user_label=&format=csv|xlsx`
(`workforce_service.task_export_rows`): one row per suggested domain w/ task
meta + DA/PA/Spam/AS + "Why suggested" + EMPTY "Backlink URL / Anchor text /
Remarks (fill in)" columns; pads blank rows up to the target so every link has
a line; Task ID + domain = stable keys. Buttons: My Work Today header
("Today's sheet" XLSX) + per-task widget (XLSX/CSV); shared
`downloadAuthed()` helper. Viewer-scoped via day_report/visible_labels.
**Submit-back is LIVE**: `POST /workforce/task-import` (multipart csv/xlsx,
any member) — `workforce_service.task_sheet_submit` parses the filled sheet
(tolerant `_sheet_col` contains-matching), routes rows by Task ID
(scope-checked per row; edited/unknown ids counted as skipped), stages one
`link_review` batch per project via `stage_link_import` (label "Task sheet —
<users> (N links)", `meta.task_sheet=true`; assigned_user_label +
placement_date + link_type from the assignment; anchor/remarks carried;
project default target applied) and `record_action(accepted, assignment_id)`
marks used suggested domains. Nothing imports until reviewer approval — the
staging gate is WHY any member may submit. UI: "Submit filled sheet" in My
Work Today header + "Submit filled task sheet" in ImportDesk (routes itself,
no project picker). (3) **Main-sheet Status column**
(`GOOGLE_MAIN_STATUS_COL="Status"`): `status_from_cell` (active/inactive word
sets; blank/typo → None = untouched; "inactive" checked before "active") in
`discover_projects` sets `Project.status` + runs the SAME
`project_service.deactivation_cleanup` as a manual pause (future assignments +
templates removed); discover returns activated/deactivated counts. Auto sync
stays ACTIVE-only; per-row manual Sync of inactive projects unchanged (by
design). NOTE: server test DB `linksentinel_test` was migrated to head (was
stuck pre-0055) — integration tests run via
`DATABASE_URL=…linksentinel_test venv/bin/python -m pytest`.

**Remaining (optional/P3):** task-sheet 2-way sync (flagged off), SMTP-based
self-serve password reset, shared saved views. Reports-builder facet selects
still top-50 single-pick (out of scope 2026-07-22). Demo rows from verification:
assignment (alex · Jul 2 · Limo Black) + approved leave (alex Jul 10–11) —
removable in the Tasks desk. Temp account `qa-ui-test@linksentinel.local`
(creds `/tmp/ls_qa_creds.txt`) — deactivate/remove when owners confirm. Open
questions PHASE-9-PLAN §15 (Q1 "QA" metric, Q2 real productivity numbers).
