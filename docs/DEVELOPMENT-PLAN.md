# LinkSentinel — Final Development Plan (Decisions Locked)

> Planning only. No production code. All previously open questions are now
> **CONFIRMED** (§3) and propagated through the design. Credentials come only from
> environment variables.

---

## 1. Executive Summary

LinkSentinel is a working backlink‑QA platform (FastAPI modular monolith, Pydantic v2,
SQLAlchemy 2.0 async, PostgreSQL 16 with month‑partitioned history, Redis + Celery,
Next.js 14). This plan sequences ten requested capabilities on top of it.

Locked decisions that shape everything:

- **Crawl egress:** IPRoyal Web Unblocker, **escalate‑on‑block** (normal crawl first,
  proxy only when blocked). Highest priority — every downstream feature needs reliable
  crawl data.
- **Ingestion:** **one global main sheet** lists project sheets; **each project sheet =
  one project** (grouped per workspace/company). **Service‑account** auth, **configurable
  column mapping**. Reuse the existing `Import`/`ImportRow` pipeline — do not build a
  parallel importer.
- **Source of truth:** the Sheet owns **input** fields; the DB owns **QA / index / report**
  fields, stats and values. **Write‑back touches system‑result columns only.**
- **Duplicate identity = `(workspace_id, source_url_normalized, target_domain)`.** This
  one rule drives duplicates, assignment history, dashboard filters and write‑back keys.
- **Index check:** Google `site:<exact source URL>` fetched **through the IPRoyal proxy**,
  **manual + weekly**. Indexed = the exact source URL appears (≥1 result).
- **Reports:** each generation is a **frozen snapshot** at generation time; history is
  retained; "latest" is simply the newest version.

**Scale reality from your volumes (≈1,000 sheets × ~1,000 rows, max 2,000):**
**~1–2 million backlink rows**, and a weekly index pass that could be **up to ~1M
`site:` queries**. Two hard consequences are designed in below: (a) **index checks are
deduplicated by source URL** (a source page's indexation is independent of target, so we
check each unique source URL once, not once per backlink); (b) **Sheets sync is spread
and quota‑throttled** across the 1,000 sheets, never run as one burst.

Build order: **Proxy → Sheets ingest → Link‑identity/Duplicates → Index → ERP dashboard
→ Reports+write‑back → hardening.**

---

## 2. Current Problem Understanding

| Stated problem | Reality in code | Action |
|---|---|---|
| Cloudflare/reCAPTCHA blocks crawls | single egress IP; render path off | Proxy egress (Feature 1) |
| Manual link import | `Import`/`ImportRow` staging exists; `google_sheets` source enum exists | Add Sheets as an import source (Feature 2) |
| No duplicate visibility | only one per‑project unique constraint | Identity + duplicate model (Feature 3) |
| QA "not versioned enough" | `crawl_results` + partitioned `backlink_history` already version every crawl | Enhance labels only (Feature 4) |
| No index checking | absent | New subsystem via proxy (Feature 5) |
| Thin dashboard | `dashboard_service` live aggregates, few filters | ERP filters (Feature 6) |
| Limited reports | `report_service` + CSV/XLSX/PDF | Versioning + Sheets write‑back (Feature 7) |

**Existing debt to settle before extending:**
- `mv_*` materialized views + `tasks.maintenance.refresh_dashboards` are **dead** (the
  dashboard is live‑query now). Decide delete vs. keep in Phase 0; don't build on them.
- Playwright render path (`crawler/render.py`, `crawl.render` queue) is **disabled** and
  has no consumer. The proxy reduces the need for it further; keep it documented as
  optional, not part of this plan.
- `schemas/auth.py` uses `str` not `EmailStr` (deliberate `.local` workaround) — fine.

---

## 3. Confirmed Decisions (LOCKED)

| # | Topic | Decision | Design impact |
|---|---|---|---|
| 1 | Google Sheets auth | **Service account** | `GOOGLE_SA_JSON` (or `_BASE64`) in env; each sheet shared with the SA email |
| 2 | Main sheet | **One global main sheet**; inner project sheets per workspace/company; **1 project sheet = 1 project** | Global main‑sheet config (system settings) + per‑project `sheet_sources` rows scoped by workspace |
| 3 | Columns | **Configurable column mapping** | Reuse `Import.column_mapping`; per‑sheet mapping UI |
| 4 | Write‑back | **System result columns only** | Strict allow‑list; never write input columns |
| 5 | Source of truth | **Sheet = input fields; DB = QA/index/report fields, stats, values** | Sync updates only input columns into DB; write‑back updates only result columns into Sheet |
| 6 | Index method | **IPRoyal proxy + Google `site:` search** | Reuse `integrations/proxy.py`; parse Google result HTML; UNCERTAIN on failure |
| 7 | Indexed definition | **Exact source URL indexed** (`site:<source_url>`, ≥1 result) | Check the **source page**, deduped by source URL |
| 8 | Index schedule | **Manual + weekly scheduled** | Celery beat weekly + on‑demand trigger |
| 9 | Proxy usage | **Normal crawl first, proxy only if blocked** | `PROXY_MODE=escalate` |
| 10 | Duplicate identity | **`source_url + target_domain`** (per workspace) | `link_identity (workspace_id, source_url_normalized, target_domain)` unique |
| 11 | Volume | **~1,000 sheets × ~1,000 rows (max 2,000) ⇒ ~1–2M backlinks** | Partition index history; dedupe index checks by source URL; throttle Sheets sync |
| 12 | "User" field | **Assigned employee from the sheet, linked to app user if a match exists** | `assigned_user_label` + `employee_code`; resolve to existing `assigned_user_id` when found |
| 13 | Report version | **Frozen snapshot at generation time**; older versions retained | Store rows/filters snapshot + file per version; `is_latest` = newest |

**Remaining real risk (acknowledged, accepted by decision #6/#7):** querying Google
`site:` — even via a residential unblocker — is fragile (HTML changes, soft‑blocks, ToS
grey area). The design treats provider/parse failures as **UNCERTAIN** (never a false
"not indexed"), caches aggressively, and throttles hard. If Google reliability becomes a
problem at 1M/week, the `serp` abstraction lets you drop in an official/paid API later
without touching callers.

---

## 4. Recommended Development Sequence

```
Phase 0  Foundation cleanup (dead matview path, document render)   small
Phase 1  Proxy crawling (IPRoyal, escalate‑on‑block)               unblocks data quality
Phase 2  Google Sheets ingest (global main → project sheets)       reuse Import pipeline
Phase 3  Link identity + duplicates + assignment history           needs multi‑sheet data
Phase 4  Index / non‑index checking (proxy site:, deduped)         needs proxy (Phase 1)
Phase 5  ERP dashboard + connected filters                         needs 2–4 data
Phase 6  Reports (versioned) + Sheets write‑back                   needs 2 + 5
Phase 7  Async / scale / observability hardening                   cross‑cutting
```

**Dependencies (text):**
```
Proxy ─► QA crawl ─► Duplicates ─► Dashboard ─► Reports ─► Sheets write‑back
Sheets‑ingest ─► Link identity ─► Duplicates ─► Assignment history ─► Dashboard
Index (proxy) ───────────────────────────────► Dashboard ─► Reports
Async/queues underlie Proxy, Sheets, Index, Reports (extend existing Celery)
```
Hard rule: don't start Phase 5 before 2–4 land, or filters get built against absent data.

---

## 5. System Architecture Plan

Extend the current shape; no new services beyond Celery queues.

```
   Global main sheet ──┐
   Project sheets ─────┤ integrations/google_sheets.py (SA auth, read + write‑back)
                       │
 Next.js UI ─► FastAPI ─► Services (sheet_sync, duplicate, index, report, dashboard)
                       │        │
                       │        ▼  PostgreSQL 16 (partitioned history)
                       │   backlink_records, crawl_results[part], backlink_history[part],
                       │   link_identity, sheet_sources, index_checks[part], index_current,
                       │   assignment_history, reports(versioned)
                       ▼
                 Celery dispatch ─► Redis broker
   queues: crawl.http.N (+proxy egress) · sheets.sync · index.check · reports · maintenance
                       │
              crawler/engine ─► (escalate) IPRoyal Web Unblocker ─► target sites / Google site:
```

**New modules (match current layout):** `integrations/proxy.py`,
`integrations/google_sheets.py`, `integrations/serp.py` (Google‑via‑proxy parser),
`services/sheet_sync_service.py`, `services/duplicate_service.py`,
`services/index_service.py`, `models/sheets.py`, `models/index.py`,
`models/link_identity.py`, `workers/tasks/sheets.py`, `workers/tasks/index.py`, new
queues in `workers/celery_app.py`.

---

## 6. Data Flow Plan

**Sheet → DB (per project sheet, throttled across 1,000 sheets):**
```
global main sheet → list of project sheets (each → project, scoped to workspace/company)
  for each project sheet (scheduled, quota‑aware):
    read rows → stage Import(google_sheets)/ImportRow → validate/normalize (mapping)
      → upsert backlink_records (INPUT columns only)
        → resolve/refresh link_identity(source_norm,target_domain)
          → duplicate_status + assignment_history (if user label changed)
            → enqueue crawl for new/changed rows
              → register unique source URL for index checking
```

**Crawl (escalate‑on‑block):**
```
crawl_batch → engine.crawl → direct fetch (HTTPS‑first)
   blocked? → proxy fetch (IPRoyal) → parse → match target → QA → score/classify
     → persist crawl_result + diff → backlink_history → alerts
```

**Index (deduped by source URL, manual + weekly):**
```
index.check(source_url) → proxy GET google.com/search?q=site:<source_url>
   → parse result presence/count → INDEXED / NOT_INDEXED / UNCERTAIN
     → index_checks row (+evidence) → index_current (latest) → diff → history
```

**Report (frozen snapshot):**
```
report(filters,type,format,target) → reports queue
   → snapshot matching rows at T → render (csv/xlsx/pdf) → store(local/s3)
     → reports row (version, is_latest, filters_snapshot, file_key)
       → download OR Sheets write‑back (result columns only, idempotent by sheet_row_ref)
```

---

## 7. Flowchart‑Style Logic (text)

**7.1 Proxy escalation (per fetch)**
```
resp = direct_fetch(url)                       # HTTPS‑first (already implemented)
if resp.status in {403,429,503} or detection.cloudflare/captcha/waf:
    if PROXY_ENABLED and not proxied: resp = proxy_fetch(url)   # IPRoyal
classify(resp)                                 # hard block after proxy → NEEDS_MANUAL_REVIEW
```

**7.2 Sheet upsert + duplicate (identity = source+target_domain)**
```
for row in project_sheet:
  s = normalize(source_url); td = registrable_domain(target_url/target_domain)
  identity = upsert link_identity(workspace, s, td)        # occurrence_count++
  bl = find backlink(project, s_norm, target_norm)
  if bl is None:
        create backlink(status=PENDING, input fields from sheet)
  else:
        update INPUT fields only; never QA/result fields
        if bl.assigned_user_label != row.user:
              assignment_history(old,new); bl.user_changed=true
  bl.link_identity = identity
  duplicate_status = classify(identity occurrences across projects/users/targets)
  register source_url for index dedupe
```

**7.3 Index verdict (exact source URL)**
```
html = proxy_get("https://www.google.com/search?q=site:" + quote(source_url))
if html is None or soft_block(html):   verdict = UNCERTAIN
elif results_contain(source_url):      verdict = INDEXED
else:                                  verdict = NOT_INDEXED
store(verdict, count, evidence_snippet, queried_at); if changed → history
```

---

## 8. Database Planning

**Reuse:** `backlink_records` (system of record), `crawl_results[part]`,
`backlink_history[part]`, `backlink_issues`, `imports`/`import_rows`. **Extend + add:**

```
link_identity                       ── identity = source + target domain (per workspace)
  id, workspace_id
  source_url_normalized, target_domain
  UNIQUE (workspace_id, source_url_normalized, target_domain)
  occurrence_count, first_seen_at, last_seen_at
  INDEX (workspace_id, source_url_normalized)      -- for source‑only lookups (index dedupe)

backlink_records (extend)
  + link_identity_id (fk)                          INDEX
  + assigned_user_label (str)                      -- sheet "User"
  + employee_code (str)
  + assigned_user_id (fk users) -- EXISTS; resolve label→app user when matched
  + link_type (str/enum)        -- [confirm canonical list during Phase 2]
  + duplicate_status (enum: unique | dup_in_project | dup_cross_project |
                            dup_cross_user | dup_diff_target | dup_same_target)
  + source_sheet_id (fk sheet_sources)             INDEX
  + sheet_row_ref (str)         -- A1/row id for write‑back
  + sheet_created_date (date)
  INDEX (workspace_id, duplicate_status)
  (existing `extra` JSONB already holds site_metrics + published_date)

assignment_history
  id, workspace_id, project_id, backlink_id (fk), link_identity_id
  old_user_label, new_user_label, changed_at, changed_by, source(sheet|ui)
  INDEX (backlink_id, changed_at)

sheet_sources                      ── one connected project sheet → one project
  id, workspace_id, project_id (fk)  UNIQUE(project_id)
  spreadsheet_id, sheet_tab, column_mapping(jsonb)
  last_synced_at, last_sync_status, last_sync_import_id (fk imports)
  writeback_enabled(bool), writeback_columns(jsonb allow‑list, RESULT columns only)
  -- global main sheet id/config lives in a single system settings row or env

index_checks                       ── history; keyed by SOURCE url (deduped)
  id, workspace_id, source_url_normalized, verdict(enum indexed|not_indexed|uncertain)
  result_count, provider('google_via_proxy'), queried_at, evidence(jsonb)
  PARTITION BY RANGE (queried_at)                  -- volume: up to ~1M/week
  INDEX (workspace_id, source_url_normalized, queried_at)

index_current                      ── latest verdict per source url (fast filtering)
  workspace_id, source_url_normalized (pk), verdict, result_count, queried_at
  -- backlink_records join on source_url_normalized → no history scan in dashboard

reports (extend)
  + version(int), is_latest(bool)  PARTIAL INDEX WHERE is_latest
  + filters_snapshot(jsonb), scope_project_id, scope_user_label
  + output_target(enum download|google_sheet), sheet_writeback_ref(jsonb)
  + row_snapshot_key (object‑storage key of the frozen rows, optional)
```

**Relationships (text ER):**
```
workspace 1─* project 1─* backlink_records *─1 link_identity
project 1─1 sheet_sources
backlink_records 1─* crawl_results[part] / backlink_history[part] / backlink_issues
backlink_records 1─* assignment_history
backlink_records *─1 index_current (by source_url_normalized) 1─* index_checks[part]
workspace 1─* reports(versioned)
imports 1─* import_rows ; imports *─1 sheet_sources (source=google_sheets)
users *─* workspaces (workspace_members RBAC); backlink_records *─1 users (assigned)
```

**Indexing / performance (at 1–2M rows):**
- Index checks deduped by `source_url_normalized` → far fewer than backlink rows
  (duplicates collapse). `index_current` gives O(1) latest lookup for filtering.
- Partition `index_checks` (and keep partitioning `crawl_results`, `backlink_history`)
  by month/week.
- Add `(workspace_id, duplicate_status)` and `(source_sheet_id)` indexes; keep existing
  grid/keyset composites.
- Sheets sync must be **incremental + throttled**: per‑sheet content hash, only changed
  rows; schedule the 1,000 sheets across the day to respect Google quotas.

**Migrations:** Alembic, one per phase. Data‑migrate `link_identity` + `index_current`
backfill from existing `backlink_records`. History tables are append‑only (no soft
delete). Soft delete (`archived_at`) only on `projects` / `sheet_sources`.

---

## 9. Feature‑by‑Feature Implementation Plan

### FEATURE 1 — Proxy Crawling (IPRoyal Web Unblocker, escalate‑on‑block)

**FEATURE GOAL:** Resolve Cloudflare/reCAPTCHA/WAF pages by retrying blocked crawls
through IPRoyal, cutting false "needs‑review" verdicts.

**CURRENT PROJECT AREA AFFECTED:** `crawler/fetch.py`, `crawler/engine.py`,
`core/config.py`, `workers/runtime.py`, `core/metrics.py`.

**USER ROLES AFFECTED:** None directly; Admin sets env.

**BUSINESS LOGIC:** `PROXY_MODE=escalate` (locked): direct first, proxy only on block.
`integrations/proxy.py` builds the httpx proxy from `IPROYAL_PROXY_HOST/PORT/USERNAME/
PASSWORD` (provider‑agnostic so a second provider can be added). One proxied retry; on
proxy error fall back to the direct result and classify honestly.

**USER FLOW:** Invisible; Admin env + restart + recheck.

**DATABASE CHANGES:** None required; optionally record `egress=direct|proxy` on
`crawl_results` (recommended for debugging).

**BACKEND CHANGES:** `integrations/proxy.py`; proxied path + escalate logic in
`fetch.py`; thread settings via `engine.py`/`CrawlConfig`; env keys + metrics + masked
logging.

**FRONTEND/UX:** Optional read‑only "egress: proxy" badge on crawl detail.

**FILES TO CHANGE:** `core/config.py`, `crawler/fetch.py`, `crawler/engine.py`,
`workers/runtime.py`, `core/metrics.py`; new `integrations/proxy.py`.

**DEVELOPMENT TASKS:** 1) env + provider abstraction; 2) proxied fetch reusing
SSRF/redirect logic; 3) escalate + retry/backoff/timeout; 4) metrics/log + egress field;
5) verify on a real Cloudflare site.

**TESTING CHECKLIST:**
- [ ] `PROXY_MODE=off` leaves the direct path unchanged.
- [ ] A 403/Cloudflare page → 200 via proxy in escalate mode.
- [ ] Proxy down → graceful fallback, honest verdict, no crash.
- [ ] Password never logged; creds only from env.
- [ ] **SSRF:** input URL re‑validated before proxying (proxy must not become an SSRF bypass).

---

### FEATURE 2 — Google Sheets Ingest (global main → project sheets)

**FEATURE GOAL:** Sync one global main sheet's project sheets into the system
(1 project sheet = 1 project, per workspace/company), replacing manual import.

**CURRENT PROJECT AREA AFFECTED:** Import pipeline + new Sheets client.

**USER ROLES AFFECTED:** Admin/Manager (connect, map, trigger); QA/Viewer consume.

**BUSINESS LOGIC:** Global main sheet config (system settings/env) lists project sheets;
each maps to a project under a workspace **[Phase‑2 task: define how a project sheet
names/links its workspace+project — by an ID column in the main sheet]**. A sync creates
`Import(source=google_sheets)` and stages rows into `import_rows`, then runs the existing
validate→upsert. Service‑account auth. Configurable mapping (`column_mapping`). Sheet =
truth for input columns; DB never overwrites QA/result columns. Per‑row content hash →
skip unchanged rows. New/changed rows enqueue a crawl and register the source URL for
index dedupe.

**USER FLOW:**
```
Admin connects main sheet (share with SA email) → system lists project tabs
  → map columns per sheet (once) → "Sync now" or scheduled (spread across the day)
    → progress (reuse import UI) → links appear; new ones auto‑crawl
```

**DATABASE CHANGES:** `sheet_sources`; add sheet/user/link‑type fields to
`backlink_records`; add `sheet_source_id` to `imports`.

**BACKEND CHANGES:** `integrations/google_sheets.py` (SA auth, batched reads,
quota/backoff); `services/sheet_sync_service.py`; `workers/tasks/sheets.py` +
`sheets.sync` queue; endpoints `POST /sheets/connect`, `POST /sheets/{id}/sync`,
`GET /sheets/{id}`. Env: `GOOGLE_SA_JSON`/`GOOGLE_SA_JSON_BASE64`, `GOOGLE_MAIN_SHEET_ID`.

**FRONTEND/UX:** "Sheets" admin page: connect, mapping UI (reuse import mapping),
per‑project sync status + last‑synced + errors.

**FILES TO CHANGE:** new `integrations/google_sheets.py`,
`services/sheet_sync_service.py`, `workers/tasks/sheets.py`, `models/sheets.py`,
`api/v1/sheets.py`; extend `workers/celery_app.py`, `models/backlink.py`,
`models/imports.py`, `core/config.py`.

**DEVELOPMENT TASKS:** 1) SA Sheets client; 2) `sheet_sources` + connect/map endpoints;
3) sync task → stage → reuse upsert; 4) row hashing + new/changed detection + enqueue;
5) **throttled scheduler** across 1,000 sheets (beat + per‑sheet stagger).

**TESTING CHECKLIST:**
- [ ] SA reads a shared sheet; clear error if not shared.
- [ ] Mapping persists; missing required column blocks sync with a message.
- [ ] Re‑sync idempotent (unchanged rows skipped via hash).
- [ ] Input‑row edits update DB without touching QA columns.
- [ ] 429/quota → backoff+jitter; 1,000‑sheet run stays within quota.

---

### FEATURE 3 — Link Identity, Duplicates & Assignment History

**FEATURE GOAL:** Surface duplicates where identity = **source URL + target domain**, and
track assigned‑user changes over time.

**CURRENT PROJECT AREA AFFECTED:** `models/backlink.py`, new identity/history models,
`services/duplicate_service.py`, dashboard, Sheets sync.

**USER ROLES AFFECTED:** Manager/QA (see/act); Admin (policy).

**BUSINESS LOGIC:** Identity `(workspace_id, source_url_normalized, target_domain)`.
- `dup_in_project` (same project — already constraint‑blocked; surface, don't silently drop)
- `dup_cross_project` (same identity, different projects)
- `dup_cross_user` (same identity, different assigned users)
- `dup_diff_target` / `dup_same_target` (same source URL, different/same target domain)
- Assignment change → append `assignment_history`, set `user_changed`.
- `link_identity.occurrence_count` + owning project/user set → `duplicate_status`.
- "User" resolves to an app user when the label/employee_code matches; else label‑only.

**USER FLOW:** Duplicate badge + filter; drill‑down lists all occurrences (projects,
users, targets) and the assignment timeline.

**DATABASE CHANGES:** `link_identity`, `assignment_history`; `duplicate_status`,
`link_identity_id`, user/employee fields on `backlink_records` (see §8).

**BACKEND CHANGES:** `duplicate_service.recompute(identity)` after sync/edit; endpoints
`GET /links/{id}/duplicates`, `GET /links/{id}/assignment-history`; dashboard filter.

**FRONTEND/UX:** Grid badge; drill‑down panel; optional Sheets highlight on write‑back.

**FILES TO CHANGE:** `models/link_identity.py`, `services/duplicate_service.py`,
`api/v1/backlinks.py`; extend dashboard + frontend grid/detail.

**DEVELOPMENT TASKS:** 1) identity model + backfill; 2) recompute logic; 3) assignment
history on sync/UI; 4) filters + drill‑down; 5) UI.

**TESTING CHECKLIST:**
- [ ] Same source+target in two projects → `dup_cross_project`.
- [ ] Same source, different target domain → `dup_diff_target`.
- [ ] Reassign → one history row + flag.
- [ ] Backfill merges identities correctly (no false merges).
- [ ] Duplicate filter correct + fast at 1–2M rows.

---

### FEATURE 4 — Backlink QA Logic (enhance existing)

**FEATURE GOAL:** Keep the working crawl→QA→score→history engine; add explicit status
**regression** semantics (2xx→4xx/5xx, link/target disappearance) and tie crawls to
report versions.

**CURRENT PROJECT AREA AFFECTED:** `qa/` engine, `services/result_service.py`,
`qa/classification.py`.

**USER ROLES AFFECTED:** QA/Manager.

**BUSINESS LOGIC:** Most exists (`_diff` emits `LINK_REMOVED`, `STATUS_CODE_CHANGED`,
`REL_CHANGED`, …; classifier → PASS/WARNING/FAIL/UNKNOWN/NEEDS_MANUAL_REVIEW). Add a
**direction‑aware regression** event/severity for 2xx→4xx/5xx; keep the current status
vocabulary (final). Record which report version consumed a crawl.

**DATABASE CHANGES:** Possibly one new `HistoryEventType` (`ALTER TYPE … ADD VALUE`).

**BACKEND CHANGES:** Small `_diff` + severity additions; ensure proxy/index data feed the
same history model.

**FRONTEND/UX:** Clearer timeline labels / transition badges.

**FILES TO CHANGE:** `services/result_service.py`, `qa/classification.py`,
`models/enums.py`, frontend detail timeline.

**DEVELOPMENT TASKS:** 1) directional regression events; 2) timeline labels; 3)
crawl↔report‑version link.

**TESTING CHECKLIST:**
- [ ] 200→404 → high‑severity regression event.
- [ ] Link disappears → `LINK_REMOVED` + alert (already wired).
- [ ] History append‑only, queryable per backlink.

---

### FEATURE 5 — Index / Non‑Index Checking (Google `site:` via IPRoyal)

**FEATURE GOAL:** Determine whether the **exact source URL** is indexed by Google, with
history + evidence, manual and weekly.

**CURRENT PROJECT AREA AFFECTED:** new `integrations/serp.py`,
`services/index_service.py`, `workers/tasks/index.py`, new models, dashboard/reports.

**USER ROLES AFFECTED:** QA/Manager.

**BUSINESS LOGIC:**
- Fetch `https://www.google.com/search?q=site:<source_url>` **through the IPRoyal proxy**;
  parse for the exact source URL. `INDEXED` if present, `NOT_INDEXED` if a valid
  zero‑result page, `UNCERTAIN` on proxy/parse/soft‑block.
- **Dedupe by `source_url_normalized`** (indexation is per source page, independent of
  target/project) — at 1–2M backlinks this collapses to far fewer unique URLs.
- **Cache:** don't re‑check a URL within the weekly window; manual re‑check overrides.
- **Throttle hard** (Redis token bucket) to avoid Google soft‑blocks; randomized delays.
- Store provider, count, queried_at, evidence snippet.

**USER FLOW:** QA picks project/links → "Check index" → queue → badges + Index report;
weekly beat job refreshes; changes tracked over time.

**DATABASE CHANGES:** `index_checks[part]` + `index_current` (keyed by source URL) — §8.

**BACKEND CHANGES:** `serp.py` (Google‑via‑proxy parser, replaceable), `index_service`,
`tasks/index.py` + `index.check` queue + weekly beat; endpoints `POST /index/check`,
`GET /index`.

**FRONTEND/UX:** Index badge on grid; Indexed/Non‑indexed filter; Index report + history.

**FILES TO CHANGE:** new `integrations/serp.py`, `services/index_service.py`,
`workers/tasks/index.py`, `models/index.py`, `api/v1/index.py`; extend `celery_app.py`,
dashboard, reports, frontend.

**DEVELOPMENT TASKS:** 1) proxy `site:` fetch + robust parser + UNCERTAIN handling; 2)
models + dedupe by source URL; 3) cache + throttle; 4) manual + weekly triggers; 5)
report + filter + UI.

**TESTING CHECKLIST:**
- [ ] Known‑indexed URL → INDEXED; nonsense URL → NOT_INDEXED.
- [ ] Soft‑block/parse failure → UNCERTAIN (never false NOT_INDEXED), retried w/ backoff.
- [ ] Re‑check suppressed within the weekly window; dedupe by source URL verified.
- [ ] Evidence + history stored; filter works at scale.

---

### FEATURE 6 — ERP Dashboard & Connected Filters

**FEATURE GOAL:** Filter across user, project, link type, follow/nofollow, index status,
duplicate status, user‑changed, date ranges, status code, QA status, link/target
found/missing, report version.

**CURRENT PROJECT AREA AFFECTED:** `services/dashboard_service.py`,
`schemas/dashboard.py`, `api/v1/dashboard.py`, `frontend/components/workspace-app.tsx`.

**USER ROLES AFFECTED:** All; RBAC‑scoped (`allowed_project_ids`).

**BUSINESS LOGIC:** AND‑combined server‑side filters over `backlink_records` joined to
`index_current`, `link_identity`, `assignment_history` and date ranges (keep live‑query).
Dependent filters return facet counts so the UI disables empty options. Each filtered
view → a Report (Feature 7) with the same filter snapshot. Summary cards + charts (status
mix, index mix, duplicates, failures over time from `backlink_history`).

**DATABASE CHANGES:** Indexes per §8 (`index_current`, `(workspace_id,duplicate_status)`).

**BACKEND CHANGES:** Composable filter builder + `GET /dashboard?…` + `GET /dashboard/facets`.

**FRONTEND/UX:** Filter bar with dependent options + counts; cards; charts; drill‑down to
pre‑filtered grid; export.

**FILES TO CHANGE:** `services/dashboard_service.py`, `schemas/dashboard.py`,
`api/v1/dashboard.py`, `frontend/components/workspace-app.tsx`, `frontend/lib/api.ts`.

**DEVELOPMENT TASKS:** 1) filter builder + facets; 2) index/duplicate joins + indexes; 3)
cards/charts; 4) "save as report"; 5) RBAC verified on every filter.

**TESTING CHECKLIST:**
- [ ] Each filter alone + combined returns correct rows.
- [ ] Facet counts match; empty options disabled.
- [ ] Viewer sees only permitted projects.
- [ ] Fast at 1–2M rows (indexed, keyset paging).

---

### FEATURE 7 — Reports (Versioned, Frozen Snapshot) + Sheets Write‑Back

**FEATURE GOAL:** ERP reports (QA, duplicates, status code, link/target missing, index,
crawl failure, sheet sync, user performance, link type), each a frozen snapshot,
exportable and writable back to project sheets (result columns only).

**CURRENT PROJECT AREA AFFECTED:** `services/report_service.py`,
`workers/tasks/reports.py`, `models/report.py`, Sheets client (Feature 2).

**USER ROLES AFFECTED:** Manager/Admin generate; QA/Viewer read/export (RBAC).

**BUSINESS LOGIC:** Each generation = a **frozen snapshot** (rows + `filters_snapshot` +
rendered file) with a `version`; history retained; `is_latest` = newest. New report types
are new queries over existing tables (renderer already does CSV/XLSX/PDF). Write‑back uses
a strict **result‑column allow‑list** (`writeback_columns`), idempotent by
`sheet_row_ref`, never touching input columns (source‑of‑truth rule).

**USER FLOW:** Filter → "Generate report" (type/format/target) → async render → download
or "Write to Sheet" → version history list with a "latest" badge.

**DATABASE CHANGES:** Extend `reports` (version, is_latest, filters_snapshot, scope,
output_target, sheet_writeback_ref, optional row_snapshot_key) — §8.

**BACKEND CHANGES:** `report_service` versioning + snapshot; new report‑type queries;
reuse `google_sheets.py` for write‑back; `tasks/reports.py` write‑back branch.

**FRONTEND/UX:** Report builder; version history; "latest" badge; write‑to‑sheet + status.

**FILES TO CHANGE:** `models/report.py`, `services/report_service.py`,
`workers/tasks/reports.py`, `api/v1/reports.py`, `integrations/google_sheets.py`,
frontend reports panel.

**DEVELOPMENT TASKS:** 1) versioning + frozen snapshot; 2) new report‑type queries; 3)
filter snapshotting; 4) Sheets write‑back (allow‑list, idempotent); 5) UI history +
regenerate.

**TESTING CHECKLIST:**
- [ ] Regenerate → new frozen version; old versions intact; `is_latest` flips.
- [ ] Each report type matches its dashboard filter.
- [ ] Write‑back touches only result columns; manual/input data untouched.
- [ ] Re‑run write‑back idempotent.
- [ ] Download works via the local‑storage streaming endpoint.

---

## 10. Testing Strategy

- **Unit (no network):** proxy escalation decision, sheet mapping/hashing, identity
  resolution, index verdict + Google‑HTML parser, report versioning — mock httpx/Sheets.
- **Integration (Postgres + Redis):** sync idempotency, assignment history, dashboard
  filters, report snapshot.
- **Fakes/contracts:** IPRoyal, Sheets, Google‑`site:` behind abstractions; inject fakes;
  no live external calls in CI.
- **E2E smoke:** project sheet → sync → crawl (proxy mock) → QA → index (mock) → report →
  write‑back; assert counts/statuses.
- **Scale check:** seed ~1M rows; verify dashboard filter latency + index dedupe counts.
- **Regression guard:** existing crawl/QA tests stay green.

---

## 11. Risk & Scalability Notes

**Security**
- All infra creds via env: `IPROYAL_*`, `GOOGLE_SA_JSON*`, `GOOGLE_MAIN_SHEET_ID`,
  `RAPIDAPI_KEY`. Never in DB/code/logs (mask). Per‑workspace secrets stay Fernet‑encrypted.
- **SSRF:** re‑validate the input URL before proxying; the proxy must not become an SSRF
  bypass (review in Feature 1).
- **Sheets least privilege:** share only required sheets with the SA; write scope only if
  write‑back enabled.
- **Google `site:` via proxy:** ToS‑grey + fragile; treat failure as UNCERTAIN, throttle,
  cache; the `serp` abstraction allows swapping to an official API later.

**Scalability (1–2M backlinks, 1,000 sheets, ~1M index checks/week)**
- **Index dedupe by source URL** is the key lever — design it in from day one.
- **Sheets sync throttling:** incremental (row hash), per‑sheet, staggered across the day
  to respect Google quotas; never one burst.
- Partition `index_checks`; keep `crawl_results`/`backlink_history` partitioned.
- Extend the existing Redis token bucket to proxy + Google calls; cap concurrency per
  provider.
- Keep live‑query dashboard but add covering indexes; only add rollups if profiling
  demands.

**Reliability / failure states**
- Wrap every external call (proxy, Sheets, Google) with retry+backoff+jitter; record
  failures as job state; never crash a batch (matches current `acks_late` + idempotent
  writes).
- Distinct states: blocked vs. error vs. provider‑error vs. uncertain — never collapse to
  "FAIL".

**Edge cases:** sheet unshared/renamed mid‑sync; column removed; duplicate rows within a
sheet; URL with/without trailing slash/scheme; user label with no app match; Google soft‑
block / ambiguous count; report generated during a sync (snapshot isolation).

---

## 12. Final Roadmap

| Phase | Deliverable | Depends on |
|---|---|---|
| 0 | Remove/park dead matview path; document render path | — |
| 1 | IPRoyal proxy (escalate‑on‑block) + SSRF review | 0 |
| 2 | Google Sheets ingest (global main → project sheets, SA, throttled) | 1 |
| 3 | Link identity + duplicates (source+target_domain) + assignment history | 2 |
| 4 | Index checking (Google `site:` via proxy, deduped, manual+weekly) | 1 |
| 5 | ERP dashboard + connected filters | 2,3,4 |
| 6 | Reports (frozen‑snapshot versions) + Sheets write‑back (result cols) | 2,5 |
| 7 | Async/scale/observability hardening | all |

**Final DB recommendation:** keep `backlink_records` / `crawl_results[part]` /
`backlink_history[part]` / `backlink_issues` / `imports` / `import_rows`; **add**
`link_identity` (source+target_domain), `assignment_history`, `sheet_sources`,
`index_checks[part]` + `index_current` (by source URL); **extend** `backlink_records`
(identity, duplicate_status, sheet refs, assigned‑user label/employee, link type, resolve
to `assigned_user_id`) and `reports` (frozen‑snapshot versioning + write‑back). Reuse
existing partitioning, RBAC scoping, Fernet secrets, env‑var infra creds, and Celery
queue topology.

**Only open implementation detail left (not blocking):** the canonical **`link_type`
value list** and **how the main sheet names a project sheet's workspace/project** (an ID
column vs. tab name) — both resolved as the first tasks of Phase 2, not before.

---

*Prepared against the current codebase. No code changed. All §3 decisions are locked.*
