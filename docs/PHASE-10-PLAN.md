# PHASE 10 — Full System Finalization

> Owner prompt (2026-07-11): link-type cleanup + master management, task-based
> source-domain recommendation engine, old-vs-current metrics, robots/blocking,
> user dashboard parity, team finalization, user calendar, complete link history,
> duplicate-aware imports, opportunity-domain workflow, copy/export everywhere,
> admin→user email, UI enhancement, branded login, RBAC, reliability.
> This doc is the work queue + requirement-traceability matrix. **Nothing in the
> owner prompt may be dropped**; every item maps to a phase below.

## Ground truth (scanned on prod 2026-07-11)

- `backlink_records.link_type`: **72 distinct values** (~20 real types), 41,334 rows.
- `link_types` catalog: mirrors the same mess (all misspellings active).
- `google_sheet_project_tabs.tab_name`: tab names ARE link-type names + a few
  non-link tabs (Targeting Keywords, Other Off-Page, Indexing Work, Live links,
  Story Submission, Target(ing) Keywords) — the migration must NOT touch those.
- `task_assignments.link_type_names` exists → tasks already carry link types.
- Full audit of every subsystem: workflow `wf_03f91503-2bc` (8 investigators).

## A. Proposed master link-type mapping (ADMIN REVIEWS BEFORE EXECUTION)

| Master (final) | Aliases found in data (count) |
|---|---|
| Social Bookmarking | Book Marking (2039) · SBM (361) · Social Bookamrking (10) |
| Article Submission | Article (1404) · Article submission (47) · article (30) |
| Web 2.0 | WEB2.0 (878) · web 2.0 (833) · WEB 2.0 (663) · web2.0 (492) · web-2.0 (285) · Web2.0 (175) · Web 2.o (82) |
| Business Listing | Business Listings (1658) · Busniess Listing (657) · Busniees Listing (447) · Business listing (223) · business listing (205) · Web-Business Listings (71) · listing (11) · Business Lisitng (6) |
| Profile & Forums | Profiles + Forums (1418) · Profile + Forums (1228) · Profile + Forum (917) · Profiles & Forums (246) · Forums & Profiles (120) · Profile Forums (45) · Forum & Profiles (30) |
| Profile | profile (358) · Profile Submission (277) · intern-profile (284) ⚠owner-review |
| Blog Post | Blog post (365) |
| GBP - Article Submission | GBP Article (48) · GMB - Article Submission (91) ⚠GMB→GBP |
| GBP - Web 2.0 | GMB Web 2.0 (59) · GBP Web 2.o (46) |
| GBP - Citations | GBP-Citation (21) |
| GBP - Business Listing | GBP Business Listing (14) · GMB Business Listings (39) |
| Image Submission | Image Sub (69) |
| Quora + PDF + Video | Quora+PDF+Video (135) · Quora + pdf+video (47) · Quora+PDF +Video (33) |
| PDF Submission | PDF (41) |
| Guest Post | Guest post (32) · Guest Posting (6) · guest post old (64) ⚠owner-review |
| Free Guest Post | Free Guest post (26) · free guest post (23) |
| Social Media | Socail Media (10) |
| Wiki Submission | — |
| Classified Ads | Classified Ads posting (26) · classified (3) |
| Forum Discussion | forum discussion (7) |
| Quora + Pinterest + Reddit | Quora+pinterest+reddit (23) |
| Article + Blog | ⚠owner-review (combo type — kept separate by default) |
| Google Maps Listing | — |
| *(non-link tabs untouched)* | Targeting Keywords · Target Keywords · Other Off-Page · Indexing Work · Live links · Story Submission |

**Rules baked in:** GBP/GMB types NEVER merge into their non-GBP counterparts
(the GBP dedup-exclusion + relaxed matching key on the "GBP"/"GMB" substring).
GMB→GBP merge proposed (Google renamed the product) — extends the GBP rules to
those rows; owner can override per-row in the review UI.

## B0. Audit-refined sequence (workflow `wf_03f91503-2bc`, 9 investigators, 2026-07-11)

The deep audit refined §B into P0–P9 (full detail in the audit output; key deltas):

- **P0 Safety rails:** verify server alembic head == local `0042`; pre-deploy pg_dump
  script in `deploy/`; baseline commit; migration template = additive/idempotent,
  chunked UPDATEs (0025 style) on partitioned tables.
- **P1 Link-type engine (FIRST — everything keys on it):** migration `0043`
  `link_types.merged_into_id` (alias/redirect layer). MUST fix
  `link_type_service.resolve_or_create` in the same deploy (filter `deleted_at IS NULL`,
  follow merge chains, survive duplicate slugs — today a soft-deleted type is
  resurrected by the next sheet sync / MultipleResultsFound crashes imports).
  `link_type_merge_service.merge_types()/rename_type()` under a pg advisory lock:
  chunked repoint `backlink_records.link_type_id` + rewrite denormalized `link_type`
  string; rewrite `link_type_productivity`, `user_productivity_overrides`
  (keep-winner-on-collision), `task_assignments.link_type_names` +
  `assignment_templates.link_type_names` (array_replace + dedup),
  `google_sheet_project_tabs.link_type_name`, `field_constants->>'link_type'`;
  scoring repoint ONLY via `scoring_config_service` locked path (one-is-latest is
  service-enforced); winner name ≤60 chars (backlink_records.link_type varchar(60)!).
  **Google tab renames AFTER DB commit, per-tab fail-open** (write-back opens tabs BY
  NAME → rename first, THEN update `backlink_records.sheet_tab`/`imports.sheet_tab`/
  `sheet_sources.sheet_tab`, guarding uq_backlink_records_sheet_entry collisions).
  GBP/GMB-boundary merges → re-run conflict detection + source-domain recompute.
  Batch-tracked, audited. Frozen snapshots (reports.filters, batch_items.payload,
  competitor_backlinks.link_type_label) stay untouched = accepted staleness.
- **P2 Domain enrichment:** `0044` — source_domains robots counts + `robots_band`
  (recompute-owned, mirrored into EVERY whitelist: _RANGE_PARAMS/_NUMERIC_FILTER_
  COLUMNS/_SORT_COLUMNS/rule _ALL_FIELDS/exports/UI); `da_first/pa_first/spam_first/
  as_first/first_metrics_at/first_metrics_source` set-once via COALESCE in ALL THREE
  writer paths (fetch_metrics, approve_items, site_metrics.enrich); metric_check_history
  old/new JSONB + ws index; opportunity 12-status lifecycle on the durable
  decisions-side-table pattern (NEVER on competitor_source_domains — recompute wipes it).
- **P3 Import finalization:** file upload for domain imports (reuse import_parse +
  preview endpoints that already exist), staged invalid/duplicate transparency,
  existing-record detail on duplicates, worker-side domain metric checks (inline cap
  = ~200 clicks for 5k domains today), funnel summary, `0045` market/country columns.
- **P4 Recommendation engine:** `0046` `domain_recommendations` (domain_key-keyed —
  survives recompute; statuses suggested→viewed→accepted/skipped; auto + manual).
  Candidates from project_view's available pool minus robots-blocked minus
  Blocked/Rejected/Used/Archived, matched on task link_type_names vs
  link_type_distribution, ranked DA/qualified%/spam.
- **P5 History unification:** `0047` backlink_history actor/role/source/note +
  new event types; emit from EVERY mutation path (create/update/override/delete-
  tombstone/bulk/import-drift/rescore/index-flip/dedup-flip/metrics); repeated checks
  exposed via GET /backlinks/{id}/checks over crawl_results (already stores every
  check); searchable paginated history API; raise RETENTION_HISTORY_DAYS→730.
- **P6 Calendar + viewer parity + team:** ONE shared TaskCalendar (day/week/month,
  month±1) replacing 3 divergent grids; viewer dashboard = REUSE admin UserDashboard
  with selfView prop (endpoints already viewer-scoped via visible_labels); My Work +
  My Dashboard tabs; anonymized team benchmark for viewers.
- **P7 Copy/export everywhere:** copyToClipboard helper (zero clipboard code today);
  server exports for dashboards/analytics/performance/workforce/audit/batches/team;
  PDF via extracted reports _to_pdf; fix Backlinks export bypassing api() token refresh.
- **P8 Email + login:** integrations/mailer.py extracted from alerts worker;
  admin→user compose (Permission.SEND_EMAILS, Notification channel=EMAIL log,
  templates in Setting KV); branding additions (announcement/colors/signup toggle —
  whitelist-only in public /auth/branding); forgot-password wiring the DORMANT
  PasswordResetToken table (anti-enumeration, single-use, revoke refresh) — gated on
  SMTP being configured.
- **P9 UI sweep + final verification + report.**

Owner decisions (8) and risks (13) recorded in the audit output; decisions surfaced
in-app at the relevant review steps.

## B. Build sequence (dependency-ordered)

| # | Phase | Covers (owner sections) | Key work |
|---|---|---|---|
| 10.1 | **Link-type standardization engine** | §1, §21, §22 | `link_type_registry` (master + aliases + status + merge history), similarity scanner (normalize→group→suggest), **admin review UI** (mapping table, per-row override, approve), executor: DB backup → transactional migration (backlink_records.link_type + link_type_id, link_types catalog, task_assignments.link_type_names, scoring scopes, saved rules/filters) → **Google Sheet tab renames via gspread** (only tabs matching an alias; audit each) → alias map kept for ingest-time normalization (like user-label merge, migration 0042 pattern). Idempotent, full before/after log, rollback from the log. Validation: new link types must come from the master list unless admin. |
| 10.2 | **Master link-type manager** | §2 | Admin desk: list/search master types, aliases, usage counts (projects/tasks/links/sheets/domains/recommendations), add/edit/merge/deactivate, change history, restore mapping. Per-type metrics/rules/description/recommendation settings. |
| 10.3 | **Domain enrichment: old-vs-current metrics + robots/blocking** | §5, §6 | `source_domains`: original_* metric columns (imported DA/PA/traffic + original link type + original data date + data source + value state old/refreshed/estimated/unavailable/manual) — populated at import, NEVER overwritten by refresh (current cols update; metric_check_history already stores deltas). Robots/blocking: `robots_status` (allowed/partially_blocked/mostly_blocked/fully_blocked/unknown/manual_review/temporarily_unavailable) + robots_checked_at + robots_detail; checker task (robots.txt fetch + parse, noindex sampling) capped/batched; desk filters; **admin override w/ mandatory reason, audited**. |
| 10.4 | **Opportunity Domain workflow** | §12, §13, §14 | Status machine on imported/candidate domains: New → Under Review → Validated → Approved/Rejected/Duplicate/Blocked/Needs Metrics/Needs Link-Type Review → Ready for Recommendation → Assigned → Used → Archived. Bulk market-list import (file+paste, CSV/Excel, column/link-type/market/country/metric mapping, preview: validation+duplicates w/ existing-record details, normalization protocol/www/path, per-row errors, downloadable error report, batch progress) building on the existing domain_import staging. Import log w/ all counts. Duplicates NEVER silently created; unique → Opportunity workflow. Filters + bulk actions + notes + owners + history. |
| 10.5 | **Recommendation engine** | §3, §4, §15 | `domain_recommendations` (domain, user_label, task/project/link_type scope, rank, reasons[], status: recommended/viewed/copied/accepted/skipped/rejected/completed, manual flag, priority, due, notes, audit). Auto-generator: read user's active task_assignments → project + link_type_names → candidate = source/opportunity domains matching link type (per-type domain classification from usage + import mapping) + project market/country + quality (DA/PA/traffic/spam) + NOT blocked (robots_status) + NOT already used in project + availability → rank + explain. Regenerates on task/domain/metric change; skipped/rejected not re-shown. Admin manual recommend from Source Domains / Opportunity / User / Task / Project / Link-Type / Recommendation pages (user/team/project/task/link type/priority/due/reason/notes, labeled MANUAL, audited). Metrics shown beside task link type + each recommended domain (DA/PA/traffic/DR/spam/refdomains/age/indexed/country/robots/last-checked/source; admin-configurable visibility). Copy + export. |
| 10.6 | **User dashboard parity + filters** | §7, §8, §18 | Viewer-scoped version of the admin UserDashboard: personal KPIs (assigned/completed/pending/overdue/rejected/QA-approved/needs-correction, links created/approved/rejected, completion/approval/rejection/rework rates, avg completion time), daily/weekly/monthly activity charts (granularity toggle from Phase-2 work), project + link-type + task-type performance, trends, targets, benchmark vs permitted team averages, recommendation usage, saved filters, drill-downs, quick copy/export. Admin-side filters extended (date/user/team/project/link type/task+link+QA+recommendation+domain status/country/market/DA-PA-traffic ranges/robots/source-vs-opportunity/imported-vs-manual/active/completed/approved). Strict self-scoping (viewer endpoints already self-scope — extend, verify). |
| 10.7 | **User task calendar** | §10 | Month±1 minimum (prev/current/next nav), day/week/month views, shows assigned tasks w/ project, link type, priority, status, due/start, overdue/completed/rescheduled markers; click → task details; responsive. Builds on the existing Tasks month calendar + week planner (already renders users×days). |
| 10.8 | **Complete link history** | §11 | Unified per-link timeline: every event (creation, edit, status change, override, QA check incl. REPEATED unchanged-outcome checks, recheck, reassignment, user/project/link-type/domain/URL changes, metric changes, notes, imports, recommendation events, dedup actions, delete/restore, automated vs manual) with actor/role/timestamp/old/new/reason/source/related task-project-domain-linktype. Implementation: widen backlink_history writes at every mutation site + merge existing streams (AssignmentHistory, metric_check_history, conflict actions, audit rows) into one queryable API + drawer History tab w/ search/filter/export. Never overwrite old rows. |
| 10.9 | **Copy/export everywhere + team finalization + email** | §9, §16, §17 | Export endpoints for: user/team stats, tasks, link history, recommendations, opportunity domains, import logs, QA/project/link-type reports, calendar, comparisons, audit logs (CSV/XLSX; PDF where useful; respect filters + RBAC). Copy buttons (domain/URL/task/recommendation/filtered set). Team desk: benchmarks, user-vs-user comparison, averages, top performers/needs-support, workload balance, upcoming/overdue. Admin→user email: SMTP-backed compose (individual/selected/team/project/task recipients, templates, custom subject/body, task/project context), permission-gated, logged w/ history, addresses hidden from unauthorized. Falls back to clear "SMTP not configured" state until SMTP_* set. |
| 10.10 | **Branded login + UI polish + final QA** | §19, §18, §20–23 | Login: brand colors/background, forgot-password (SMTP self-serve; hidden until SMTP configured), password visibility toggle, validation/loading/error states, admin-controlled announcement, responsive. Permission matrix test per role; large-dataset perf pass; final report (features, DB changes, sheet/tab changes, mappings, migration/duplicate/import results, recommendation logic, permission matrix, testing, limitations, rollback, future work). |

## C. Owner decisions pending
1. Mapping rows marked ⚠ (intern-profile, guest post old, Article + Blog, GMB→GBP) — decided in the review UI before execution.
2. SMTP credentials (needed for §17 email + §19 forgot-password; both ship disabled-with-notice until set).
3. Sheet tab renames touch the LIVE Google Sheets — executed only after mapping approval, tab-by-tab, logged.

## D. Reliability rules (apply to every phase)
DB backup before each migration · additive/nullable schema changes · transactional
executors · idempotent (re-run safe) · full before/after logs · rollback path ·
no silent failures · no history overwrites · RBAC on every new endpoint · tests
per phase · deploy → verify → commit per phase.
