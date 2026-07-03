# PHASE 9 — Production-Maturity Plan (Owner-Meeting Requirements)

> Status: **PLANNING — approved sections become the work queue.**
> Sources: owner/team meeting notes (2026-07) converted into a technical plan, audited
> against the live codebase (migrations 0001–0019, 124 passing tests, Phases 0–8 live).
> Companion docs: `PHASE-8-PLAN.md` (delivered), `HANDOFF.md` (architecture).
>
> Golden rule for this phase: **refine, connect, and mature — do not rebuild.**
> Everything below is mapped to what already exists; net-new work is marked **NEW**.

---

## 1. Executive Summary

LinkSentinel already ships the hard core: async crawl + QA engine (47 checks),
dynamic versioned scoring (global → workspace → link-type → project), canonical-URL
duplicate detection with cross-user/cross-project classification, multi-tab Google
Sheets sync + write-back, dynamic analytics with whitelisted filters, versioned
reports (CSV/XLSX/PDF incl. pivots), split company/project dashboards, alerts,
source-domain aggregates with Moz/RDAP metrics, a competitor gap-analysis MVP,
JWT auth with 4 roles, dark mode, and URL-persisted project context.

Phase 9 turns that engine into a polished operations product. The gaps are
**not** core algorithms; they are: (1) a **unified batch/run system** with progress,
logs, counters, and in-app (not download-only) reports; (2) a **metric freshness
layer** ("Checked recently", 10/20/30-day recheck, check history, cache-hit
counters); (3) **Sheets-style multi-select filters**, toasts, tooltips, and plain-
English statuses with a "Why?" everywhere; (4) duplicate **new-vs-previous**
batch accounting on top of the existing conflict engine; (5) competitor →
**opportunity lifecycle** (used/converted/excluded) with metric reuse and export;
(6) **user performance** dashboards driven by daily **task-assignment snapshots**,
link-type productivity settings, a working-days calendar and leave workflow; and
(7) role hardening (TeamLead scope, admin-only user creation, closed signup).

Nothing here requires breaking the Sheets sync, the scoring engine, or existing
data; every schema change is an additive Alembic migration.

## 2. Product Vision

**One tool where an SEO agency runs its entire backlink operation** — ingest from
the sheets the team already uses, verify every link automatically, explain every
verdict in plain English, price every link's quality against configurable rules,
find the next opportunities from competitors, and measure people fairly against
what they were actually assigned that day. Non-technical staff must never need a
developer to understand *what happened, why, and what to do next*.

Design north stars: **explainable** (every status has a "Why?"), **frugal**
(never pay for the same API answer twice), **accountable** (every run is a batch
with logs, counters and history), **contextual** (company vs project vs user
views never mix), and **calm** (compact tables, quiet colors, progress you can
see).

## 3. PRD (by module)

Format: Goal → What exists → Requirements (numbered, testable). "Exists ✅"
items still get the UX/wording pass.

### 3.1 Filters & tables (foundation)
Goal: Google-Sheets-grade filtering on every major table.
Exists: single-select dropdown facets w/ live counts (analytics/reports), preset
chips + search + sort on Backlinks, server-side whitelisted filters.
Requirements:
- R1 `FilterMultiSelect` component: search-within, select-all/clear, selected
  count badge, "(Blanks)" option, scrollable, keyboard-navigable.
- R2 Backends accept multi-value filters (`status=FAIL,WARNING` or repeated
  params) for: status, link type, user, project, source domain, batch, index,
  duplicate type. Analytics `_FILTERS` gains `*_in` variants (whitelisted ANY()).
- R3 Blanks filtering (`(none)` sentinel → `IS NULL`).
- R4 Column visibility menu on the Backlinks table (persisted per browser).
- R5 Sticky header + horizontal scroll (exists) + compact density retained.
- R6 Quick filters (chips, exists) + "Advanced" popover combining all controls.

### 3.2 Statuses, wording & tooltips
Goal: every status answers *what/why/next* for a non-technical user.
Exists: 47 issue codes with messages+recommendations stored per link; status
badges; detail drawer shows issues + score breakdown.
Requirements:
- R7 Central `STATUS_HELP` map (frontend) — label, plain-English description,
  "what to do next" — rendered by a reusable `InfoTip` on every badge.
- R8 "Needs Review — because X": list rows surface `top_issue_label` as the
  reason inline (e.g. "Needs review · bot protection on source"), tooltip lists
  all failing rules from `backlink_issues`.
- R9 Plain-English renames (display only, no enum changes): NEEDS_MANUAL_REVIEW
  → "Needs Review", UNKNOWN → "Couldn't check (temporary)", duplicate scopes →
  "Same project duplicate / Used by another project / Used by another user",
  index uncertain → "Index unclear", cache hits → "Checked recently".
- R10 Metric cells show `fetched_at` age ("2d ago") with cache/fresh origin.

### 3.3 Notifications (toasts)
Exists: top Notice bar, in-app Notification center (filters/stats/mark-read).
Requirements:
- R11 Toast stack (bottom-right, auto-dismiss, success/info/error variants),
  replacing the single Notice line; all `onNotice` call sites route through it.
- R12 Long-running actions (sync, import, duplicate scan, re-score, index check,
  report) fire started → progress (poll) → completed/failed toasts, with a
  "View details" action deep-linking to the batch/report.

### 3.4 Unified batch system
Goal: everything that runs is a **batch** with progress, logs, counters, history.
Exists: `imports`+`import_rows` (row snapshots + errors!), `crawl_jobs`
(processed/succeeded/failed), sheet-sync status fields on `sheet_sources`,
report versions, notification records. Missing: one registry + logs + counters.
Requirements:
- R13 **NEW** `batches` table (kind: import | sheet_sync | writeback | crawl |
  recheck | index_check | duplicate_scan | rescore | competitor_import |
  competitor_check | report), status pending/running/completed/failed/partial,
  totals JSONB `{total,done,ok,failed,skipped}`, counters JSONB
  `{api_calls,api_cached,dup_new,dup_previous}`, project/user/meta, timestamps.
- R14 **NEW** `batch_logs` (batch_id, ts, level, message, row_ref, data JSONB).
- R15 Existing runners (import worker, sheet sync, crawl dispatch, conflict
  rebuild, rescore, index sweep, report worker) create/update their batch row —
  additive wrapper, no behavioral change to the runners themselves.
- R16 Batches desk: list + filters (kind/project/user/status/date), detail view
  with progress bar, counters, logs, row errors; retry action where safe
  (failed import rows, failed report).
- R17 `GET /batches`, `GET /batches/{id}`, `GET /batches/{id}/logs` (+ SSE or
  3-second polling for progress — polling first, SSE later).

### 3.5 Google Sheets sync UX
Exists: multi-tab discovery/sync, per-tab imports with row errors, write-back,
last_sync status/error on the source. Verified: `GET /imports/{id}/errors`
(CSV download) exists; row snapshots already stored in `import_rows.raw`.
Requirements:
- R18 Sync creates a `sheet_sync` batch (per run) + child import batches per
  tab; SheetsDesk shows live progress (rows total/done/ok/failed, current tab).
- R19 **In-app error report**: `GET /imports/{id}/errors.json` (paginated) and
  an ErrorReport panel (row #, error, offending cells) — download stays.
- R20 Reproduce & fix the reported **500 on error-report download** (suspect:
  frontend `<a href>` lacks the Authorization header → actually 401/500 via
  nginx, or JSON serialization edge). Fix + regression test.
- R21 Write-back records a batch; failures list exact rows + reason; a re-sync
  after write-back must be proven idempotent (test).
- R22 "Why stopped" surfaced: import/sync batch error shown verbatim with a
  plain-English prefix.

### 3.6 Metric caching / freshness / recheck
Exists: Redis TTL cache in `site_metrics` (+ negative caching), per-link
`extra.metrics.fetched_at`, source-domain Moz/RDAP fetch (0013), serper index
checks; crawl QA itself is free (our crawler).
Requirements:
- R23 **NEW** `metric_check_history` (entity kind domain|page, key, provider,
  outcome, fetched_at, batch_id, from_cache bool) — audit + counters source.
- R24 Freshness service (`services/metric_service.py`): `should_recheck(entity,
  freshness_days, force)`, `get_domain_metrics(domain, freshness_days)`,
  `get_page_metrics(url, freshness_days)` — thin façade over existing
  integrations, consulting stored `fetched_at` before any network call.
- R25 Recheck controls: Backlinks filter "checked older than 10/20/30 days" (UI
  over existing `checked_to`) + bulk actions "Recheck older than N days" and
  "Force recheck" (existing recheck endpoints + N-day server-side selection).
- R26 In-batch dedup: one API call per unique domain per batch (pass a per-batch
  memo through the enrich path); counters recorded on the batch (R13).
- R27 Competitor→project reuse: when a competitor domain is later added as a
  backlink, domain metrics are reused if fresh (page-level checked only if that
  exact URL lacks fresh page metrics).
- R28 UI: every metric shows age + origin (cache/fresh) (R10).

### 3.7 Source domains (project-wise)
Exists: global `source_domains` aggregates (+ per-domain metrics, drill-down),
`source_domain_id` on every backlink, per-project counts derivable.
Requirements:
- R29 Project view of source domains: used-by-this-project (with counts) vs
  known-globally-but-unused-here ("Available — not used in this project yet").
- R30 "**New for this project**" definition (owner rule): a backlink whose
  source domain had no prior backlink *in that project* counts as project-new,
  even if the domain exists globally. Computed per batch at import time and
  stored on the row event (`import_rows` flag) + batch counters; user analytics
  aggregate from it.
- R31 "New globally" = first backlink ever for that domain (workspace-wide).
- R32 Per-user attribution: new-domain counts by user (import row → user label).

### 3.8 Duplicates (new vs previous, batch-wise)
Exists: canonical fingerprints, conflict groups + members, scope classification
(same_project/cross_project/cross_user), resolve/ignore, rebuild endpoint,
duplicate filters on Backlinks, `import_rows.raw` snapshots.
Requirements:
- R33 Batch accounting: each import/sync batch stores `dup_new` (conflicts first
  created by this batch) vs `dup_previous` (row matched an already-known
  conflict) — additive columns on conflict members (`first_seen_batch_id`).
- R34 Duplicate report **in-app**: filterable table (batch, project, user,
  domain, type, new/previous, date) showing why-duplicate, where the original
  lives (project/user/batch), old row vs new row snapshot side-by-side.
- R35 Scan scopes: "this sheet's URLs only" vs "everything" (existing rebuild +
  a URL-scoped variant).
- R36 Dashboard: duplicate trend chart (by week) + by-project/by-user splits
  (analytics group-by already supports user/project — add conflict counts).

### 3.9 Scoring (verify & polish — mostly exists)
Exists ✅: per-parameter points, link-type + project overrides w/ inheritance,
versioned rule sets, 0–100 clamp, stored per-verdict breakdown, batch re-score
(preview/apply), Scoring desk. Requirements:
- R37 Score tooltip in the Backlinks list (params used, weights, contributions,
  final) — data already in `crawl_results.score_breakdown`; surface it.
- R38 Display bands relabel: Good (80+), Average (60–79), Weak (30–59),
  Failed (<30), Needs Review (review statuses) — display map over GradeBand.
- R39 Guard: sum of positive contributions capped at 100 (already clamped;
  add a UI hint in the Scoring desk when configured points could exceed 100).

### 3.10 Competitors & opportunities (v2)
Exists: paste-ingest sheets, canonical fingerprints, per-domain existing-vs-new
comparison, Competitors desk. Requirements:
- R40 **NEW** named `competitors` entity (per project: name, site, notes);
  uploads attach to a competitor; 1k+ links handled batch-wise (R13).
- R41 Opportunity lifecycle on `competitor_source_domains`: status open |
  used | excluded | dismissed (+ reason, decided_by/at, used_backlink_id).
  Adding a project backlink from that domain auto-marks **used** (hook in
  import path), keeps history, and removes it from the active list.
- R42 Guest-post handling: competitor link-type tag (from sheet column or
  manual); "Guest Post" filterable/excludable in the opportunity list.
- R43 Metrics for competitor domains via R24 (reuse-first); DA/AS columns in the
  opportunity table.
- R44 Export opportunities: CSV download + write to a Google Sheet tab (reuse
  `google_sheets.write_back` machinery).
- R45 Every competitor check is a batch with history (R13).

### 3.11 Dashboards (global + project + user)
Exists ✅ split dashboards; project deep view (link types, trends, top domains,
regressions, team); analytics engine w/ date ranges. Requirements:
- R46 Global additions: totals strip (projects, links, domains, users, batches,
  duplicates, indexed), timeframe picker (30d default / 3m / 6m / 12m / all /
  custom) + **compare vs previous period** (delta chips), links-by-week chart,
  new-domains-by-week, status donut, duplicate trend, project comparison table,
  API usage (calls vs cache-hits from R13 counters).
- R47 Project additions: domains used vs available (R29), opportunities summary,
  manual-review list with reasons, recent batches.
- R48 **NEW User performance dashboard** (desk): per-user new links, project-new
  vs global-new domains (R30/31), indexed %, duplicates caused, by-status/type
  splits, task completion (R51), timeframe + compare-previous + user-vs-user.
- R49 Charts implemented with the existing lightweight bar/donut patterns (no
  heavy chart lib) unless owners approve a dependency.

### 3.12 Tasks, productivity, calendar, leave (net-new module)
Requirements:
- R50 **NEW** `link_type_productivity` (global per link type: minutes-per-link
  or links-per-hour) + `user_productivity_overrides`.
- R51 **NEW** `task_assignments`: (date, user, project, hours, link_type_ids[],
  expected_links — computed from hours × productivity, editable). The row **is**
  the immutable daily snapshot: performance for a date always uses that date's
  rows. Actuals = links created that day by that user/project (import
  attribution), completion % stored nightly (beat job) and recomputed on demand.
- R52 **NEW** `working_days` (workspace calendar: date, is_working) — month grid
  admin UI; defaults editable by clicking dates.
- R53 **NEW** `leave_requests` (user, date range, reason, status
  pending/approved/rejected, decided_by/at). Approved leave removes that day's
  expectation (excluded from denominator); absence without leave counts against
  completion; rejected leave keeps the requirement.
- R54 Task board: Admin/TeamLead assign per day (copy-from-yesterday helper);
  User sees "My day" (projects, hours, link types, expected vs done).
- R55 Optional (flagged, default off): task schedule import from a Google Sheet
  tab; write-back only behind explicit confirmation (owners accepted skip-able).

### 3.13 Roles & auth
Exists: JWT (15m access / 7d rotating refresh), roles admin/manager/qa/viewer,
per-project membership scoping (`allowed_project_ids`), team desk (invite,
role, activate), audit log.
Requirements:
- R56 Role mapping (display-level + permission tweaks): Admin=admin,
  **TeamLead**=manager + **NEW** `teamlead_users` assignment (which users they
  see); User=qa (task view, own performance, leave requests); viewer stays.
- R57 TeamLead scoping: performance/tasks endpoints restrict to assigned users;
  projects already restricted via memberships.
- R58 **Close public signup**: `ALLOW_PUBLIC_REGISTRATION=false` once a
  workspace exists (bootstrap-safe); Team desk "Create user" (admin, sets temp
  password) + password reset flow (token model exists — verify email path or
  admin-handed reset link).
- R59 Sheets auto-user mapping stays suggestion-only (Employees desk approve).

### 3.14 Reports in-app
Exists: versioned generation, download, pivot types, templates, date ranges.
Requirements:
- R60 In-app viewer: for completed reports render the stored file (CSV/XLSX)
  as a paginated table (`GET /reports/{id}/rows?offset=`) — no regeneration.
- R61 All Phase-9 "reports" (sync/error/duplicate/batch/user-performance) are
  **screens first** (filterable tables), export second.

## 4. SRS (condensed)

Functional: FR-1 Multi-select/blank filters on Backlinks, Analytics, Duplicates,
Batches, Opportunities, Notifications (R1–R6). FR-2 Status tooltips with
what/why/next on every badge (R7–R10). FR-3 Toasts for lifecycle events (R11–12).
FR-4 Batch registry + logs + counters for all 11 run kinds (R13–17). FR-5 Sheets
sync progress + in-app row errors + fixed download (R18–22). FR-6 Freshness
service, 10/20/30/force recheck, per-batch API dedup, history (R23–28). FR-7
Project-wise source-domain usage + project-new/global-new counters (R29–32).
FR-8 Duplicate new-vs-previous per batch + in-app report + trend (R33–36). FR-9
Scoring tooltip + bands + 100 cap verified (R37–39). FR-10 Competitor entities,
opportunity lifecycle, guest-post exclusion, exports, metric reuse (R40–45).
FR-11 Dashboards incl. compare-previous + user performance (R46–49). FR-12
Tasks/productivity/calendar/leave with immutable daily snapshots (R50–55).
FR-13 TeamLead scope, closed signup, admin user creation, reset flow (R56–59).
FR-14 In-app report viewing (R60–61).

Non-functional: NFR-1 all new queries tenant-scoped + whitelisted (no raw
interpolation — house rule). NFR-2 additive migrations only; zero data loss;
every migration reversible. NFR-3 batch writes chunked; no request handler holds
a transaction > a few seconds (heavy work in Celery). NFR-4 UI stays responsive
at 100k links (keyset pagination exists). NFR-5 p95 < 500ms for list endpoints
at current data scale. NFR-6 plain-English copy reviewed against §3.2 map.
NFR-7 dark mode + mobile pass for every new screen. NFR-8 tests: unit for
freshness/dup-accounting/task-snapshot math; API tests for new endpoints; suite
stays green (124 → grows).

## 5. Information Architecture

Company context (no project): Overview (global dash) · Analytics · Backlinks ·
Duplicates · Source Domains · Competitors* · Batches **NEW** · Imports · Sheets ·
Alerts · Reports · **Team performance NEW** · Tasks **NEW** (admin/TL) ·
Calendar **NEW** (admin) · Team · Employees · Scoring · Settings.
Project context (selected): Dashboard · Backlinks · Duplicates · Source Domains
(project view) · Competitors & Opportunities · Batches (project-filtered) ·
Imports · Analytics · Reports · Alerts · Tasks (project view) · Scoring
(project) · Settings. User role sees: My Day (tasks) · My Performance · My
Leave · Backlinks (assigned projects) only. (*Competitors are per-project;
company view shows cross-project rollup.)

## 6. Feature modules → work items

| Module | Exists | Phase-9 work |
|---|---|---|
| Filters/tables | facets, chips, search | FilterMultiSelect, multi-value backends, blanks, column visibility |
| Statuses/wording | issue codes, drawer | STATUS_HELP + InfoTip, inline reasons, renames |
| Toasts | notice bar, notif center | toast stack + lifecycle events |
| Batches | imports/crawl_jobs/rows | registry+logs+counters, desk, retry |
| Sheets sync | multi-tab, errors CSV | progress, in-app errors, 500 fix, idempotency test |
| Metrics | Redis TTL, fetched_at | history table, freshness façade, recheck UX, in-batch dedup |
| Source domains | global aggregates | project used/available, project-new logic + counters |
| Duplicates | conflict engine | first_seen_batch, new-vs-prev, in-app report, trend |
| Scoring | full engine ✅ | list tooltip, band labels, >100 config hint |
| Competitors | gap MVP | entities, lifecycle, guest-post, export, metric reuse |
| Dashboards | split + deep project | timeframe compare, charts, user perf desk |
| Tasks/calendar | — | full net-new module (R50–55) |
| Roles/auth | 4 roles, JWT | TeamLead map, closed signup, create-user, reset |
| Reports | files + templates | in-app viewer, report screens |

## 7. Database changes (all additive; migrations 0020+)

- 0020 `batches` + `batch_logs`; add `batch_id` (nullable FK-less UUID, indexed)
  to `imports`, `crawl_jobs`, `reports`.
- 0021 `metric_check_history`; index (entity_kind, key, fetched_at).
- 0022 duplicates accounting: `backlink_conflict_members.first_seen_batch_id`,
  `backlink_conflicts.first_detected_batch_id`; backfill NULL (pre-Phase-9).
- 0023 competitors v2: `competitors` table; `competitor_backlinks.competitor_id`,
  `.link_type_label`; `competitor_source_domains` + status/reason/decided_by/at/
  used_backlink_id + da/semrush columns.
- 0024 workforce: `link_type_productivity`, `user_productivity_overrides`,
  `task_assignments` (immutable-by-date), `working_days`, `leave_requests`.
- 0025 `teamlead_users` (manager_user_id, member_user_id, UNIQUE pair).
- 0026 import row flag: `import_rows.is_project_new_domain bool` +
  `imports.new_domain_count` (counters for R30).
- Config keys: `ALLOW_PUBLIC_REGISTRATION`, `METRIC_FRESHNESS_DAYS_DEFAULT=10`,
  `TASK_SHEET_SYNC_ENABLED=false`.
- Explicitly NOT added (covered by existing): scoring_profiles/rules (→
  scoring_parameters/rule_versions), duplicate_issues (→ conflicts),
  batch_row_snapshots (→ import_rows.raw), domain_metrics (→ source_domains +
  history), notifications/reports (exist).

## 8. API changes

New: `GET /batches`, `GET /batches/{id}`, `GET /batches/{id}/logs`;
`GET /imports/{id}/errors.json`; `POST /backlinks/recheck-stale {days|force}`;
`GET/PUT /metrics/freshness-config`; `GET /source-domains/project-view?project_id`;
`GET /duplicates/report` (filterable, incl. new/previous);
`POST/GET /competitors/entities`, `PATCH /opportunities/{id}` (use/exclude/
dismiss), `POST /opportunities/export`; `GET /performance/users`,
`GET /performance/users/{id}`; `POST/GET /tasks/assignments`,
`GET /tasks/my-day`; `GET/PUT /calendar/working-days`; `POST/GET/PATCH
/leaves`; `POST /team/users` (admin create), `POST /auth/request-reset` +
`POST /auth/reset`; `GET /reports/{id}/rows`.
Changed (backward-compatible): list endpoints accept comma multi-values +
`(blanks)`; sync/import/rescore/index responses include `batch_id`; register
returns 403 when `ALLOW_PUBLIC_REGISTRATION=false` and a workspace exists.

## 9. UI/UX improvements (component inventory)

New shared components: `FilterMultiSelect`, `ToastProvider/useToast`, `InfoTip`,
`StatusBadge` (badge+reason+tip), `AgeStamp` (fetched_at ago + origin),
`BatchProgress` (bar + counters), `DataTable` upgrades (column menu, sticky),
`ReportTable` (in-app viewer), `MonthCalendar` (working days / leave),
`ComparePill` (+12% vs prev). Wording pass per §3.2. Every new screen: loading
skeleton, empty state with next-step CTA, error state with retry, dark mode.

## 10. Workflow diagrams (text)

W1 Sheet sync: START → create batch(sheet_sync) → list tabs → per tab: read →
stage rows (snapshot) → validate → dup-check (mark new/prev, project-new) →
upsert → log row errors → update batch progress → END batch (counters: rows,
ok, failed, dup_new, dup_prev, api_calls, api_cached) → toast + in-app report.
W2 Metric fetch: need metric → history/stored fresh? (≤N days) → reuse (mark
"Checked recently", count cache-hit) → else in-batch memo? → reuse → else API →
snapshot + history(from_cache=false) → save.
W3 Recheck-stale: user picks 10/20/30/force → server selects matching links →
crawl batch (R13) → progress → toast.
W4 Opportunity: competitor upload batch → canonicalise → per-domain compare →
open opportunities → user adds backlink from domain (any path) → hook marks
used (+history, reuse metrics) → excluded/guest-post filtered out.
W5 Task day: admin assigns (date,user,project,hours,types) → expected links
from productivity → day passes → nightly job computes actuals from imports →
completion% frozen with that day's assignment → dashboards read snapshots;
approved leave removes the day from the denominator.
W6 Duplicate accounting: row → fingerprint → existing conflict? → member with
first_seen_batch=this → dup_prev++ (or new conflict → dup_new++) → batch report.

## 11. Development roadmap (maps owners' phases → ours)

Owners' Phase 1 (audit/plan) = this document. Then:
- **A (P0) UI foundation**: toasts, FilterMultiSelect, InfoTip/STATUS_HELP,
  Backlinks wiring, wording pass.
- **B (P0) Batch + logs**: 0020, wrap runners, Batches desk, sync progress,
  in-app import errors + 500 fix.
- **C (P0) Metrics freshness**: 0021, façade, recheck-stale, in-batch dedup,
  AgeStamp.
- **D (P1) Source domains + duplicates**: 0022+0026, project view,
  project-new counters, dup new-vs-prev, in-app dup report, trend.
- **E (P1) Competitors v2**: 0023, lifecycle, guest-post, export, reuse.
- **F (P1) Dashboards**: timeframe+compare, charts, user performance desk.
- **G (P2) Workforce**: 0024+0025, tasks, productivity, calendar, leave,
  TeamLead scoping, closed signup + create-user + reset.
- **H (P2) Reports in-app** viewer + report screens polish.
- **I (P3) Optional**: task-sheet 2-way sync, API-usage analytics, shared saved
  views, user theme prefs.
Each increment ships alone: build → migrate → test → deploy → verify → commit
(house workflow), UI increments build-gated.

## 12. Priority matrix

**P0** toasts · multi-select filters · status reasons/tooltips · batch registry
+ desk · sync progress + in-app errors + 500 fix · freshness façade + recheck
stale + in-batch dedup. **P1** project-new domain logic · dup new-vs-prev +
report + trend · competitor lifecycle/export · global dash compare + charts ·
user performance desk. **P2** tasks/productivity/calendar/leave · TeamLead +
closed signup + reset · in-app report viewer · column visibility. **P3**
task-sheet sync · API-usage dash · shared views · theme prefs.

## 13. Risks & dependencies

1. `workspace-app.tsx` ≈ 5k lines — new desks go in `frontend/components/desks/`
  (extract-on-touch; no big-bang refactor). 2. Live prod, shared box — keep the
  per-increment deploy loop; batch wrappers must be fail-open (a logging bug
  must never fail a sync). 3. Sheets write-back idempotency — regression test
  before touching. 4. Serper/Moz quotas — freshness layer *reduces* spend;
  counters make it visible. 5. Task attribution (which user "created" a link)
  relies on sheet user labels/employee mapping — accuracy depends on Employees
  desk mappings (flagged to owners). 6. Closed signup lock-out — bootstrap
  bypass when zero workspaces. 7. Performance snapshots immutable → correct by
  design, but backfilling history before go-live is impossible (starts at zero).
  8. "QA" metric (owners' DA/PA/**QA**) is undefined — treated as our QA score
  unless clarified (Q1). 9. Compare-previous math on sparse data (div-by-zero →
  "n/a"). 10. Polling progress adds load — 3s interval, only while a batch runs.

## 14. Future enhancements

SSE/WebSocket live progress; shared (workspace-level) saved views & templates;
Ahrefs/Majestic providers behind the same freshness façade; anomaly alerts
("indexed % dropped 15%"); client-facing read-only report links; mobile PWA for
My Day; per-workspace branding/white-label; billing/plan limits when SaaS-ified.

## 15. Open questions (need owner answers; safe defaults chosen)

1. **"QA" metric** in "DA/PA/QA" — is that our QA score, or a third-party
  metric? *Default: our QA score.*
2. Productivity baselines per link type (e.g. Profile 30/hr, Web2.0 5–7/hr) —
  need the real list for all 7 types. *Default: seeded editable guesses.*
3. Task attribution source of truth: sheet `user` column via Employees mapping,
  or in-app assignee? *Default: sheet user label (current data reality).*
4. Leave: half-days needed? *Default: full days only.*
5. Opportunity quality rules (min DA? exclude spam>X?) *Default: none — filter
  UI only, rules later.*
6. Working-week default before admin edits the calendar. *Default: Mon–Sat
  working, Sunday off.*
7. Should TeamLead create/edit task assignments or only view? *Default: can
  assign for their users on their projects.*
8. Report retention/purge policy for batches & logs. *Default: keep 12 months.*
9. Guest-post detection: sheet column, or manual tag only? *Default: manual +
  optional sheet column if present.*
10. Task-sheet 2-way sync: owners said skip-able — confirm skip for Phase 9.
  *Default: in-app only (P3 flag).*
