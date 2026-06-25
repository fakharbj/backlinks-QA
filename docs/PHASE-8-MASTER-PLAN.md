# LinkSentinel — Master Development Plan (Phase 8, v2)

> **Supersedes & extends** `docs/PHASE-8-PLAN.md`. Adds: URL **canonicalization +
> SHA-256 fingerprint** system, **store-don't-skip duplicates** with conflict
> tracking, **Semrush + Moz + domain-age** metrics per source main domain,
> **aggregate index/non-index counters** (no full scans), **multi-workspace/company**
> hardening, **Redis-free** caching + background jobs, and large-DB indexing best
> practices.
>
> **This is a planning document only — no production code, no implementation, no
> guessing.** Tags: `✅ CONFIRMED` (derivable from code/your requirements) ·
> `🟦 RECOMMENDED` (my design where options exist) · `❓ NEEDS CONFIRMATION`
> (a business/architecture decision only you can make). The §11A "Dynamic
> Filtration & Reporting" registry from the prior plan still applies and is
> referenced throughout — every entity/field below must be filterable + reportable.

---

## 1. Executive Summary

This phase turns LinkSentinel into a **large-scale, multi-tenant off-page SEO
operations platform** built on three new foundations:

1. **Canonical‑URL + Fingerprint core.** Every URL (project backlink *and*
   competitor) is canonicalised, hashed to a SHA‑256 **fingerprint**, and resolved
   against an indexed `canonical_urls` table **before** storage or comparison.
   Duplicate detection becomes an O(log n) B‑tree lookup, and — critically —
   **duplicates are stored, not skipped**, and surfaced as **conflicts** in
   filters/reports.
2. **Source‑domain intelligence with cached third‑party metrics.** Source URLs
   group into source main domains; each domain carries **Moz DA/PA**, **Semrush
   Authority Score / monthly traffic / keywords**, and **domain age**, fetched
   **per domain** (never per URL), stored in DB, refreshed on a schedule.
   Index/non‑index ratios are read from **stored aggregate counters**, never by
   scanning links.
3. **Competitor/opportunity engine.** Competitor sheets (stored separately) are
   fingerprinted, compared against our source domains (existing vs new),
   auto‑categorised by link type, scored as opportunities, and promoted to
   assignable tasks for the off‑page team.

Cross‑cutting: **multi‑workspace isolation** (already present — hardened),
**dynamic scoring** (global → workspace → project → link‑type → parameter,
versioned, frozen in reports), **dynamic filtration + reporting registry** (one
declaration → filter + facet + group‑by + report column + report filter),
**Redis‑free** caching/jobs (DB‑backed), **soft delete + audit everywhere**, and
**large‑DB indexing** discipline.

**Biggest architectural decisions in this phase (must be confirmed — §5):**
the fingerprint/duplicate model change, the Redis‑free job queue, multi‑workspace
"company" layering, and whether scoring re‑computes history.

### What already exists and is REUSED (not rebuilt)

| Capability | In code today | Plan |
|---|---|---|
| Multi‑tenant workspaces | `Workspace`, `WorkspaceMember` (M:N user↔workspace), `workspace_id` on every table | **Reuse/harden** — add UI switcher + optional company layer |
| URL canonicalisation | `crawler/normalize.py` (https, strip www, strip tracking, lenient slash, drop fragment, sort query, IDN) | **Reuse** as the canonicaliser feeding the fingerprint |
| SHA‑256 identity | `duplicate_service.identity_key` = sha256(workspace|src|tgt_domain) | **Evolve** into `canonical_urls.fingerprint` |
| Source registrable domain | `normalize.registrable_domain()` + `backlink_records.source_domain` | **Reuse**; add `source_domains` table + platform‑host rule |
| Third‑party metrics | `integrations/site_metrics.py` (Similarweb/Moz RapidAPI/Moz official, provider‑abstracted) | **Extend** with Semrush + domain‑age providers; move storage to DB tables |
| Reports + versioning | `reports.version`/`is_latest` | **Extend** with true frozen snapshots |
| Audit | `audit_logs` + `audit_service.record()` | **Reuse** for delete + change audit |
| Analytics dimensions | `analytics_service.py` whitelist | **Unify** with report filters via one dimension registry (§11A) |

### What must CHANGE (verified in code)

- **Dedup model:** unique constraint `(project_id, source_url_normalized,
  target_url_normalized)` + import logic **merge/skip** same‑(source,target) rows.
  → Replace with `canonical_urls` + `backlinks.canonical_url_id` + **conflict**
  records; stop skipping.
- **Redis usage:** broker + RedBeat + robots cache + metrics cache + rate limiter.
  → Move caches to DB; replace the job system (Celery+Redis) with a Postgres‑backed
  queue (`🟦`/`❓`).
- **Metrics storage:** today written into `backlink.extra['metrics']` per backlink.
  → Move to per‑domain tables.
- **Ratios:** computed live. → Move to stored aggregate counters.

---

## 2. Current Problem Understanding

### 2.1 Verified current behaviour (the baseline we build on)

- **Workspaces are already multi‑tenant.** `Workspace` + `WorkspaceMember` (M:N),
  `workspace_id` FK on all business tables, RBAC scoping in `core/deps.py`/`rbac.py`.
  A user can already belong to many workspaces; `/auth/me` returns memberships.
  **Gap:** no UI workspace switcher; no "company > workspace" hierarchy; some new
  features must remember to carry `workspace_id`.
- **Import dedup (verified in `import_service._process_row`):**
  - Within one import batch, a `seen` set drops exact `(src.normalized,
    tgt.normalized)` repeats (`status=DUPLICATE`, not stored).
  - Against the DB, an `existing` lookup on `(project_id, source_url_normalized,
    target_url_normalized)` → **Google Sheets**: updates input fields *in place*
    (no new row, records assignment‑change history); **CSV/manual**: marks
    `DUPLICATE`, no new row.
  - `link_identity` (sha256 of `workspace|src_norm|tgt_domain`) tracks
    cross‑project/user duplicate *rollups* (`duplicate_status`), recomputed per
    touched identity. **But same‑(source,target) inside a project is one row.**
- **Canonicalisation (verified in `normalize.py`):** `normalize_url` →
  `normalized` = https‑pinned, www‑stripped, tracking‑params dropped + sorted,
  fragment dropped (unless `#!`), lenient trailing slash, IDN→punycode. This is a
  solid canonical form already.
- **Metrics:** `site_metrics.py` fetches Similarweb/Moz (RapidAPI or official),
  Redis‑cached per domain, written into `backlink.extra['metrics']`. Prod is
  `SITE_METRICS_PROVIDER=similarweb`.
- **Index check:** `index_checks` table, deduped by source URL, denormalised onto
  `backlink_records.index_status`. No per‑domain aggregate counters.
- **Jobs:** Celery on Redis (broker db1 / result db2 / RedBeat). Robots cache,
  metric cache, per‑domain rate limiter all in Redis.

### 2.2 Existing debt / risks to fix this phase

1. **`backend/app.zip`** tracked + stale → `.gitignore` + `git rm --cached`.
2. **Filter logic duplicated** (analytics_service vs report worker) + hardcoded
   report columns → unify via dimension registry (§11A).
3. **Dead `qa` Celery queue** (declared, unused). If we keep Celery, use it for
   re‑scoring; if we move to a DB queue, drop it.
4. **LinkIdentity rollup freshness** depends on the import calling `recompute`;
   any non‑import write path can leave stale `duplicate_status`. The new aggregate
   counters (§ feature 14) must avoid the same trap (transactional update + nightly
   reconcile).
5. **Reports aren't truly frozen** (worker reads live `backlink.score`). Add
   snapshots.
6. **`api` PM2 process ~300 restarts** — investigate before heavier endpoints.
7. **Metrics in `extra` JSONB** can't be filtered/indexed well → move to columns/
   tables.

---

## 3. Confirmed Logic (from your requirements + the code)

- Every workspace/company has isolated data; every project belongs to a workspace;
  every business row carries `workspace_id`. **(exists)**
- Each project has **one or more** main target domains.
- **All URLs are canonicalised before storage/checking; every canonical URL has a
  SHA‑256 fingerprint; duplicate detection uses the fingerprint.**
- **Duplicates are NOT skipped** — they are stored and marked duplicate/conflict,
  and appear in filters/reports/Sheets export.
- Source URLs group by **source main domain**; analytics exist globally,
  per‑project, and per‑workspace.
- Link types come from **project‑sheet sub‑sheet (tab) names**; user chooses which
  tabs import/QA/ignore via checkboxes.
- Scoring is **dynamic, parameter‑based, versioned**, with global → project (→
  workspace, → link‑type) overrides; **reports store frozen score snapshots**.
- Third‑party metrics (**Moz DA/PA, Semrush AS/traffic/keywords, domain age**) are
  stored **per source main domain**, cached in DB, refreshed on schedule, fetched
  via async jobs, keys from env.
- Index/non‑index **ratios are read from stored aggregate counts**, not by scanning
  all backlinks.
- Competitor sheets attach to projects; competitor backlinks are **stored
  separately**, also fingerprinted; compared (existing vs new); auto‑categorised by
  link type; promoted to assignable **opportunities**.
- **Redis is excluded as a cache this phase** → DB indexed tables instead.
- Soft delete + audit logs where possible.

## 4. Recommended Logic (my design where options exist)

- **Fingerprint = `sha256(canonical_url)`**, where canonical_url is
  `normalize_url(raw).normalized`. Store fingerprint **without** workspace in the
  hash so the same page is one canonical row globally; scope **conflict detection**
  to workspace (and optionally project) so no cross‑tenant leakage. `🟦`
- **`canonical_urls`** is a global dimension table (id, fingerprint UNIQUE,
  sample_url, registrable/source_domain_id, total_uses, first/last_seen). Both
  `backlinks` and `competitor_backlinks` reference it by `canonical_url_id`. `🟦`
- **"Same entry vs new duplicate":** a Google‑Sheet **re‑sync of the same sheet
  row** updates in place (keyed by `sheet_source_id + tab + row_ref`), so re‑syncs
  don't multiply rows; **two different rows** that share a fingerprint are stored as
  **separate** backlinks and grouped into a **conflict**. `🟦` (confirm the
  "same‑entry" key — `❓`).
- **Conflict scopes:** `same_project`, `cross_project`, `cross_user`,
  `cross_workspace` (off by default), `competitor_vs_project`. Conflict has a
  `resolution_status` (open/acknowledged/resolved/ignored). `🟦`
- **Redis‑free jobs:** Postgres‑backed queue (`background_jobs` + `FOR UPDATE SKIP
  LOCKED` workers) + a DB scheduler table; robots/rate‑limit state in DB or
  in‑process. `🟦` (vs keep Redis only as broker — `❓`).
- **Metrics live on the domain**, in dedicated tables keyed by `source_domain_id`
  (`domain_authority_results`, `semrush_domain_metrics`, `domain_age_results`) +
  history tables; aggregated onto `source_domains`/metrics tables for fast reads.
- **Aggregate counters** (`indexed_count`, `not_indexed_count`, `uncertain_count`,
  `total`, by domain × project × workspace) updated **transactionally** when an
  index verdict changes, plus a **nightly reconcile** job for self‑healing. `🟦`
- **One dimension registry** drives filters + facets + group‑by + report columns +
  report filters + UI (§11A). `🟦`
- **Company layer:** treat **workspace = company/tenant**; add an **optional**
  `companies` parent only if a company owns multiple workspaces. `🟦` (`❓`).
- **Competitor links never auto‑create users.** They belong to the competitor
  sheet/source. Only an **approved opportunity** is assignable to an internal user.
  `🟦` (matches your recommendation).

## 5. Missing Information / Needs Confirmation `❓`

> Development of the dependent feature is blocked until answered. Restated in §22.

1. **(Redis):** confirm scope. Cache‑only removal (keep Celery broker) — fast,
   low‑risk — **or** full Redis removal → Postgres job queue (recommended for
   "no Redis", but a real re‑architecture)? → blocks the async strategy (§17).
2. **(Fingerprint canonical rule):** lowercase the **whole** URL path or only the
   domain? Drop **all** query params or only tracking params? Always drop the
   fragment? (The current normalizer lowercases host only, drops *tracking* params,
   drops fragment, lenient slash.) → blocks §12.
3. **(Same‑entry key):** what makes two sheet rows "the same record to update" vs
   "a new duplicate to store"? Proposed: `sheet_source_id + tab + row_ref`. → blocks
   the import change (feature 10).
4. **(Conflict scope):** should duplicates ever be detected **across workspaces**,
   or strictly within a workspace/project? → blocks §13.
5. **(Main domain matching):** does the project main domain **replace** each link's
   own target, or **validate** it? One or many primary? → blocks features 2, 11, 27.
6. **(Company layer):** workspace = company, or a `companies` parent owning many
   workspaces? → blocks §9.
7. **(Domain grouping):** group Web‑2.0 hosts (`user.blogspot.com`) under
   `blogspot.com`, or per‑subdomain? → blocks features 11–13, 27–28.
8. **(Metrics providers & budget):** confirm Moz **and** Semrush via RapidAPI
   (endpoints/plans) + domain‑age provider + monthly quota/cost ceilings. → blocks
   §18, features 21–23.
9. **(Scoring model & freeze):** weighted‑parameter (recommended) vs configurable
   severity; re‑score history on rule change or keep versioned+frozen? → blocks
   features 17–20, reports.
10. **(Employee code rules):** unique per workspace? multiple codes per user?
    reassignable? → blocks feature 3.
11. **(Sheet layout):** confirm tabs = link types, same columns per tab; a sample
    spreadsheet would remove all ambiguity. → blocks features 5–7.
12. **(Delete policy):** which entities soft‑delete; restore window; project delete
    = archive‑keep‑history vs delete‑all? → blocks feature 35.
13. **(Saved filters/templates scope):** per‑user vs shared workspace? → blocks
    §11A saved filters.

---

## 6. Recommended Development Sequence

Six sub‑phases; each ships green and independently. Hard edges in §7.

| Sub‑phase | Theme | Features |
|---|---|---|
| **8.0 Platform** | Redis‑free + registry + workspace hardening | 38 (jobs), §11A registry, 1 (workspace), 36 (audit), 35 (safe delete) |
| **8.1 Identity core** | Canonical + fingerprint + don't‑skip dupes | 8 (canonical/fingerprint), 9 (conflicts), 10 (import change), 26 (competitor fingerprint) |
| **8.2 Foundations** | Settings, users, link types, sheets | 2 (project+main domain), 3 (users/codes), 4–7 (sheets+tabs+link types) |
| **8.3 Source‑domain intel** | Extraction, aggregates, metrics | 11, 12, 13, 14 (counters), 21 (Moz), 22 (Semrush), 23 (domain age) |
| **8.4 Scoring** | Dynamic scoring | 17, 18, 19, 20 |
| **8.5 Competitor/Reports** | Opportunity engine + ERP reports | 24, 25, 27, 28, 29, 30, 31, 32, 33, 34 |

(QA crawl **15** and index check **16** already exist — extended in 8.3 to feed
counters; not net‑new.)

---

## 7. Feature Dependencies

```
8.0 Platform ─────────────────────────────────────────────────────────────┐
  Postgres job queue (38) ─ dimension registry (§11A) ─ workspace harden (1)│
  ─ audit (36) ─ safe delete (35)                                           │
        │ (everything runs on these)                                        │
        ▼                                                                    │
8.1 Identity core                                                            │
  canonical_urls + fingerprint (8) ─► conflicts (9) ─► import no‑skip (10)   │
  └────────────────────────────────────────────► competitor fingerprint (26)│
        │ (fingerprint feeds dedup, source domains, competitor compare)      │
        ▼                                                                    │
8.2 Foundations                                                              │
  project settings + main domain (2)   users/employee codes (3)             │
  sheets main (4) ─► project/sub‑sheet sync (5) ─► tab→link‑type (6,7)       │
        │ (link_types catalog needed by scoring + competitor categorisation)│
        ▼                                                                    │
8.3 Source‑domain intel                                                      │
  source_domains (11) ─► global/project analytics (12,13)                   │
  aggregate counters (14) ◄─ index check (16)                               │
  Moz (21) + Semrush (22) + domain age (23) ─► metrics on domains           │
        │                                                                    │
        ▼                                                                    │
8.4 Scoring (17–20)  ── uses link_types + DA/Semrush parameters ────────────┘
        │ (score feeds reports/analytics)
        ▼
8.5 Competitor + Reports
  competitor upload (24) ─► map/validate (25) ─► fingerprint (26, from 8.1)
   ─► existing‑vs‑new (27) ─► auto link‑type (28) ─► QA categorise (29)
   ─► opportunity (30) ─► off‑page board (31)
  reports + versioning (32) ─ ERP filters (33) ─ Sheets export (34)
```

---

## 8. Full System Architecture Plan

Keeps the **modular monolith** (FastAPI API + workers sharing models/services/
config). Major change: the **worker runtime** moves from Celery/Redis to a
Postgres‑backed queue (`❓1`). New backend modules:

```
backend/app/
├── core/
│   └── jobs/                 (NEW) DB-backed queue: enqueue, claim (SKIP LOCKED), scheduler
├── services/
│   ├── canonical_service.py        (NEW) canonicalise + fingerprint + canonical_urls upsert
│   ├── conflict_service.py         (NEW) duplicate/conflict detection + resolution
│   ├── workspace_service.py        (EXTEND team) workspaces/companies, switching
│   ├── project_settings_service.py (NEW) settings + main domains
│   ├── employee_service.py         (NEW) users/codes/mappings
│   ├── link_type_service.py        (NEW) catalog + tab mapping
│   ├── sheet_tab_service.py        (NEW) sub-sheet detect/select
│   ├── source_domain_service.py    (NEW) extraction + aggregate counters
│   ├── domain_metrics_service.py   (NEW) Moz + Semrush + domain age (wraps integrations)
│   ├── scoring_rules_service.py    (NEW) versioned scoring resolution
│   ├── competitor_service.py       (NEW) upload/compare/categorise/opportunity
│   ├── dimensions/registry.py      (NEW) the §11A single source of truth
│   └── delete_service.py           (NEW) soft delete + preflight + restore
├── integrations/
│   ├── site_metrics.py             (EXTEND) + semrush provider
│   └── domain_age.py               (NEW) domain-age provider (whois/RapidAPI)
├── jobs/ (or workers/)             (REWORK) tasks become DB-queue handlers
└── models/  (NEW model files — §15)
```

Frontend: split new desks out of the 2,210‑line `workspace-app.tsx` into
`components/desks/*` (Workspace switcher, Settings, Source Domains, Competitors,
Conflicts, Audit), all reading the dimension registry for filters/columns.

---

## 9. Multi-Workspace / Company Architecture

**Already present:** `workspaces`, `workspace_members` (M:N user↔workspace, with
`role`), `workspace_id` on every business table, RBAC + project scoping in
`core/deps.py`. **This is the isolation backbone — reuse it.**

**To add:**
- **UI workspace switcher** (the active workspace context already flows through
  `AuthContext`; expose switching + remember last).
- **Optional company layer** `❓6`: `🟦` `companies(id, name, …)` with
  `workspaces.company_id` FK (nullable). Workspace stays the **isolation unit**;
  company is only a reporting/grouping parent for agencies running multiple
  workspaces. If a workspace already == a company for you, skip this.
- **Isolation rule (enforced, mandatory):** every query filters by `workspace_id`
  (via `AuthContext`); every new table has `workspace_id` (except truly global ones
  like `canonical_urls`, `domain_authority_results`, `domain_age_results`, which are
  **domain‑intrinsic** and safe to share — but **conflicts/backlinks** that
  reference them stay workspace‑scoped). Cross‑workspace duplicate detection is
  **off by default** (`❓4`).
- **Settings hierarchy:** global defaults → workspace settings → project settings
  (scoring, link types, column mappings). Resolver picks the most specific.

**Flowchart (workspace/company creation):**
```
START
→ Admin creates company (optional) / workspace
→ Create workspace row (+ company_id if used)
→ Add creator as workspace_member role=ADMIN
→ Seed workspace defaults (link types, scoring global→workspace copy, settings)
→ User switches active workspace → AuthContext.workspace_id changes
→ ALL subsequent queries scoped to that workspace_id
→ END
```

---

## 10. Data Flow Plan

1. **Sheet → canonical → store (no skip):** read tab rows → canonicalise source &
   target → fingerprint → upsert `canonical_urls` → upsert/insert `backlinks`
   (same sheet row updates in place; new rows stored even if fingerprint exists) →
   conflict detection groups same‑fingerprint rows → extract source domain → bump
   aggregate counters.
2. **Crawl/QA:** unchanged engine → verdict → on index‑status change, adjust domain
   aggregate counters transactionally → score via versioned rules.
3. **Metrics:** per new source domain → enqueue Moz + Semrush + domain‑age jobs →
   store on domain tables + history → aggregate onto `source_domains`.
4. **Competitor:** upload → canonical+fingerprint (separate tables) → compare
   fingerprints/domains vs ours → existing/new → auto link‑type → opportunity.
5. **Reports/analytics:** dimension registry → filter/facet/group‑by (shared) →
   report worker builds dynamic columns → frozen snapshot → export
   (CSV/XLSX/PDF/Sheets).

---

## 11. Flowchart-Style Logic (all 20)

**11.1 Workspace/company creation** — see §9.

**11.2 Project creation + main domain setup**
```
START → create project under workspace → add ≥1 main domain (project_domains, one primary)
→ validate each domain is a valid registrable domain; dedup within project
→ seed project_settings (scoring profile, status bands) → audit → END
```

**11.3 Google Sheet project sync**
```
START → for each project in main sheet → resolve project + sheet connection
→ list worksheets (tabs) → for each ENABLED tab → read rows → (11.5 canonical)
→ (11.6 conflict) → upsert/insert backlinks (NO skip) → (11.10 source domain)
→ (11.11 counters) → update sync state/history → END
```

**11.4 Sub-sheet / link-type detection**
```
START → list tabs by stable gid → upsert google_sheet_project_tabs
→ new tab → needs_mapping ; renamed (same gid) → update name ; deleted → mark missing (keep data)
→ admin sets import/QA/active + tab→link_type → save mappings → END
```

**11.5 URL canonicalisation + fingerprint**
```
START → raw URL → normalize_url() → IF invalid → record error, stop
→ canonical = normalized form (https, no-www, no-tracking, no-fragment, lenient slash, IDN)
→ fingerprint = sha256(canonical) → look up canonical_urls.fingerprint (B-tree, unique)
→ IF exists → reuse canonical_url_id, total_uses += 1
→ ELSE → insert canonical_urls(fingerprint, sample_url, source_domain_id) → END
```

**11.6 Duplicate / conflict detection**
```
START (a backlink with canonical_url_id) → find other backlinks/competitor rows with same canonical_url_id
→ IF none (besides self) → status unique → END
→ ELSE → determine scope (same_project | cross_project | cross_user | competitor_vs_project)
→ get-or-create backlink_conflicts(canonical_url_id, project_id, scope, resolution_status=open)
→ add this row to conflict_members → mark each member is_duplicate + conflict_status
→ surface in filters/reports → END
```

**11.7 User & employee-code mapping**
```
START → admin manages users + employee_codes → collect distinct (sheet label, code) from backlinks
→ suggest mapping (exact > code-match > unmapped) → admin confirms → user_employee_mappings
→ optional backfill assigned_user_id → audit → END
```

**11.8 Backlink QA crawl** (existing engine, unchanged)
```
START → claim due backlink (job queue) → crawl (https-first → googlebot → proxy → render)
→ parse → QA checks → composite verdict → score (versioned rules) → persist crawl_results
→ on index/status change → (11.11 counters) → history events → alerts → END
```

**11.9 Index / non-index checking**
```
START → select due source URLs (dedup by source) → query SERP (serper) → verdict indexed|not|uncertain
→ store index_check_results → denormalise onto backlinks.index_status
→ adjust source-domain aggregate counters (old bucket -1, new bucket +1) → END
```

**11.10 Source main-domain extraction**
```
START → canonical host → IF host in PLATFORM_HOST_LIST → key = full host (or host+seg)
→ ELSE key = registrable domain → upsert source_domains(workspace?, key) → link backlink.source_domain_id → END
```

**11.11 Source main-domain aggregate metric update**
```
START (a backlink's index verdict or membership changes)
→ BEGIN TX → UPDATE source_domain_project_metrics SET indexed_count/not_indexed_count/total accordingly
→ UPDATE source_domain_workspace_metrics likewise → COMMIT
→ (nightly) reconcile job recomputes counts from facts to self-heal drift → END
```

**11.12 Scoring calculation**
```
START → link_type known → resolve rule set (project+type → project → workspace → link_type → global), version V
→ extract parameter outcomes (http, link_found, dofollow, indexed, duplicate, DA band, Semrush AS band, age, ...)
→ score = normalised weighted sum → apply fixed hard-fail rules → band → store score + rule_version V on crawl_results → END
```

**11.13 Competitor sheet upload**
```
START → choose project → upload file / connect sheet → create competitor_sheets + import run
→ validate (≥ source URL col) → stage rows → (11.5 canonical/fingerprint) → store competitor_backlinks (separate)
→ extract competitor_source_domains → enqueue compare (11.14) + metrics (11.16) → END
```

**11.14 Existing vs new source-domain comparison**
```
START → load our source_domains set for the project → for each competitor source domain D:
→ IF D ∈ ours → category EXISTING (+ our count, indexed%, link types, score, DA/Semrush, users)
→ ELSE → category NEW_OPPORTUNITY (+ competitor URLs, est. link type, DA/Semrush, indexed%)
→ also flag EXACT-URL match via fingerprint (already_used) → write competitor_domain_comparisons → END
```

**11.15 Auto link-type categorisation (competitor)**
```
START → for competitor source domain D → look up our link_type(s) for D
→ unseen → UNKNOWN/new ; exactly one → inherit (HIGH confidence) ; multiple → AMBIGUOUS (candidates, LOW)
→ allow manual override (store auto value + manual value + source + confidence) → END
```

**11.16 Moz / Semrush / domain-age metrics fetch**
```
START → for each domain needing metrics → IF fresh in DB within TTL → reuse
→ ELSE enqueue background job (staggered) → call provider via RapidAPI (env key) →
  on success → upsert domain_authority_results / semrush_domain_metrics / domain_age_results + append history
  on failure/quota → mark stale, retry w/ backoff, never block analytics
→ aggregate latest onto source_domains → END
```

**11.17 Competitor opportunity report generation**
```
START → select project + scope (new|existing|all) + min DA/AS + link types
→ pull comparisons + metrics + index → opportunity_score = f(DA, AS, traffic, indexed%, our gap, link-type value)
→ rank, group existing/new → render (dynamic columns) → frozen snapshot → optional Sheets export → END
```

**11.18 Google Sheets report export**
```
START → report ready + output_target=google_sheet → choose spreadsheet/tab
→ create/locate results tab → write_table (never overwrite input cols) → record export → confirm (outward-facing) → END
```

**11.19 Safe delete confirmation**
```
START → delete entity E → preflight dependent counts → confirm modal (counts + type-to-confirm for high impact)
→ project delete → archive(keep history) | delete links+history (❓12) → soft delete (deleted_at/by) → audit
→ restore within window → purge job after window (hard delete) → END
```

**11.20 Aggregate metric rebuild job**
```
START (scheduled/nightly or on-demand) → for each (workspace, source_domain[, project])
→ recompute indexed/not_indexed/uncertain/total + dofollow/dup/avg_score from facts (single grouped query)
→ UPDATE metrics tables → log drift corrected → END
```

---

## 12. URL Canonicalization and Fingerprint Logic

**Goal:** one true identity per page. Raw URL → canonical URL → SHA‑256 fingerprint
→ indexed lookup. Reuse `crawler/normalize.py` (already correct for most rules).

**Canonicalisation rules (current behaviour → recommendation):**

| Rule | Today (`normalize_url`) | Recommendation `🟦` / `❓` |
|---|---|---|
| Scheme | pins `https` in match form | keep: `http`→`https` for identity `✅` |
| `www.` | stripped in match form | keep: strip `www.` `✅` |
| Trailing slash | lenient (strips except root) | keep lenient `🟦` (confirm always‑strip? `❓2`) |
| Tracking params | dropped (utm_*, gclid, fbclid, …); others kept + sorted | `🟦` keep only‑tracking‑dropped (preserves meaningful `?id=`); confirm "drop ALL params" `❓2` |
| Fragment | dropped (unless `#!`) | keep dropped `✅` |
| Case | host lowercased; **path case preserved** | `🟦` keep path case (paths are case‑sensitive on many servers); confirm lowercase‑all `❓2` |
| IDN | punycode/ASCII | keep `✅` |
| Encoding | decode+re‑encode (equivalent encodings compare equal) | keep `✅` |
| Invalid/unsupported scheme | returns `valid=False` + error | record as error row, never store a bad canonical `✅` |

**Fingerprint:** `fingerprint = sha256(canonical_url_utf8).hexdigest()` (64 hex
chars). Stored once in `canonical_urls.fingerprint` with a **UNIQUE B‑tree index**
(the single most important index in the system — §16).

**Storage split:** keep the **raw URL** on the backlink (`raw_url` /
`source_page_url`) for crawling/audit; the **canonical URL + fingerprint** live on
`canonical_urls`; `backlinks.canonical_url_id` FK joins them. (Mirrors the ER
diagram you shared.)

**Cross‑project canonical sharing:** `canonical_urls` is **global** (fingerprint has
no workspace) → the same page is one row, `total_uses` counts references. **Conflict
detection** then scopes by workspace/project so tenants never see each other's rows
(`❓4`).

**Flow (canonical):** see §11.5. **Edge cases to confirm (`❓2`):** lowercase whole
path? drop all query params? always strip trailing slash? — these change which URLs
collapse together, so they're business decisions, not defaults.

---

## 13. Duplicate Detection Logic

**Principle (changed):** never skip. Store every row; detect sameness by
fingerprint; group duplicates into a **conflict**; expose everywhere.

**The "same entry vs new duplicate" distinction (critical `❓3`):**
- **Same sheet entry re‑synced** (key = `sheet_source_id + tab + sheet_row_ref`) →
  **update in place** (no new row). Prevents row explosion on every sync.
- **Different rows, same fingerprint** → **store separately**, group as duplicates.

**Duplicate/conflict scenarios → how each is represented:**

| Scenario | Detection | Representation |
|---|---|---|
| Same raw URL | same canonical → same fingerprint | conflict member |
| Different raw, same canonical | same fingerprint | conflict member |
| Same fingerprint, same project | scope=`same_project` | conflict (same_project) |
| Same fingerprint, different projects | scope=`cross_project` | conflict (cross_project) |
| Same fingerprint, different users | scope=`cross_user` | conflict + assignment note |
| Same fingerprint, different employee code | scope=`cross_user` | conflict, code recorded |
| Same fingerprint, different target domain | conflict + `target_mismatch` flag | conflict member w/ flag |
| Same source main domain, different page | NOT a duplicate (different fingerprint) | grouped only at domain level |
| Competitor URL already in our backlinks | competitor fp ∈ our canonical_urls | `already_used` (comparison) |
| Competitor domain exists, exact URL new | domain match, fp not in ours | `new_url_existing_domain` |
| Same backlink re‑appears next sync | same‑entry key | update in place (no dup) |
| Same fingerprint, different link type | conflict + `link_type_mismatch` | conflict member w/ flag |
| User assignment changed | `assignment_history` (exists) | history event, not a conflict |

**Tables:** `canonical_urls`, `backlinks`(+`canonical_url_id`,`conflict_status`),
`backlink_conflicts`(canonical_url_id, project_id, scope, resolution_status,
detected_at, resolved_by/at), `backlink_conflict_members`(conflict_id, backlink_id).
(Matches your ER diagram; `link_identity` is **superseded** by this — plan a
migration that backfills `canonical_urls` from existing `source_url_normalized` and
rebuilds conflicts.)

**Resolution flow:** conflict starts `open` → user acknowledges/keeps‑one/ignores →
`resolved_by`/`resolved_at` recorded → still visible in history. **Filters/reports:**
`conflict_status`, `conflict_scope`, `resolution_status`, `is_duplicate` are all
first‑class dimensions (§11A).

---

## 14. Database Relationship Planning (before final schema)

**Main entities:** workspaces (tenant) → projects → backlinks → canonical_urls
(global) → source_domains → metrics (DA/Semrush/age) ; competitor_sheets →
competitor_backlinks → competitor_source_domains → comparisons → opportunities ;
scoring_rule_versions ; reports/snapshots ; jobs/audit.

**Key relationships:**
- `workspaces 1─N projects 1─N backlinks` (all carry `workspace_id`).
- `backlinks N─1 canonical_urls` (global identity); `competitor_backlinks N─1
  canonical_urls` (shared identity space → enables exact‑URL competitor match).
- `canonical_urls N─1 source_domains` (a page belongs to one source domain).
- `backlinks N─1 source_domains` (denormalised FK for fast domain analytics).
- **M:N** `users ↔ workspaces` (`workspace_members`), `users ↔ projects`
  (`project_members` / `user_projects`), `users ↔ employee_codes`
  (`user_employee_mappings`, time‑boxed), `backlinks ↔ conflicts`
  (`backlink_conflict_members`), `link_types ↔ projects` (enable).
- `source_domains 1─N metric tables` (DA, Semrush, age) + history tables.
- `source_domains` has **aggregate counter** children:
  `source_domain_project_metrics`, `source_domain_workspace_metrics`.
- `competitor_source_domains ↔ source_domains` via `competitor_domain_comparisons`
  (the insight bridge).
- `opportunities N─1 competitor_domain_comparisons`, `opportunities N─1 users`
  (only when assigned).

**Cross‑cutting requirements:** soft delete (`deleted_at`/`deleted_by`) on
user‑facing tables; audit on all mutations; versioning for scoring + reports;
report snapshots (frozen rows); aggregate counters for ratios; JSON only for
flexible settings/rule bodies (never for filterable fields).

---

## 15. Final Recommended Database Structure

> Conventions: `UUIDPrimaryKeyMixin` + `TimestampMixin`, `workspace_id` FK on all
> tenant tables, native enums via `pg_enum`, migrations `0007+` (one per sub‑phase).
> Global (domain‑intrinsic) tables omit `workspace_id`. Soft‑delete = `deleted_at`,
> `deleted_by`. Types indicative.

**Platform & tenancy**
- `companies`(id, name) — optional `❓6`.
- `workspaces`(+`company_id?`) — **exists**.
- `workspace_members`(workspace_id, user_id, role, UNIQUE(ws,user)) — **exists**.
- `users` — **exists**; `user_projects`(user_id, project_id, role) = existing
  `project_members`.

**Settings & catalogs**
- `projects`(+ soft delete) — **exists**.
- `project_settings`(project_id UNIQUE, scoring_profile, status_thresholds JSONB,
  index_expected, …).
- `project_domains`(project_id, domain, is_primary, UNIQUE(project,domain),
  partial UNIQUE(project) WHERE is_primary).
- `link_types`(workspace_id, name, slug, is_global, is_active, default_value_weight,
  UNIQUE(ws,slug)).
- `employee_codes`(workspace_id, code, is_active, UNIQUE(ws,code) `❓10`).
- `user_employee_mappings`(workspace_id, user_id?, employee_code_id?,
  sheet_user_label?, is_current, effective_from/to).

**Identity & links (the core)**
- `canonical_urls`(id, **fingerprint CHAR(64) UNIQUE**, sample_url,
  source_domain_id FK?, total_uses, first_seen_at, updated_at) — **global**.
- `backlinks` (= today's `backlink_records`, extended): `canonical_url_id` FK,
  `raw_url`(source), `target_canonical_url_id?`, `source_domain_id` FK,
  `link_type_id` FK?, `assigned_user_id` FK?, `employee_code_id` FK?,
  `qa_status`, `score`, `index_status`, `is_duplicate`, `conflict_status`,
  `sheet_source_id?`, `tab_id?`, `sheet_row_ref?`, soft delete. **Drop** the old
  `(project, src_norm, tgt_norm)` UNIQUE; replace with the same‑entry key
  `UNIQUE(sheet_source_id, tab_id, sheet_row_ref)` (partial, where sheet‑sourced).
- `backlink_assignments`(= `assignment_history`, extended with employee_code_id).
- `backlink_conflicts`(id, canonical_url_id FK, project_id FK?, workspace_id, scope,
  resolution_status, detected_at, resolved_by?, resolved_at?).
- `backlink_conflict_members`(id, conflict_id FK, backlink_id FK, added_at,
  UNIQUE(conflict_id, backlink_id)).
- `backlink_qa_results`(= `crawl_results`, partitioned; + `scoring_rule_version_id`).
- `backlink_qa_history`(= `backlink_history`, partitioned).
- `index_check_results`(= `index_checks`).

**Source domains & metrics**
- `source_domains`(id, workspace_id?, domain_key, grouping, registrable_domain,
  UNIQUE(workspace?,domain_key)) — `❓` global vs per‑workspace grain.
- `source_domain_project_metrics`(source_domain_id, project_id, backlink_count,
  indexed_count, not_indexed_count, uncertain_count, total, dofollow_count,
  duplicate_count, avg_score, link_type_distribution JSONB, last_recomputed_at,
  UNIQUE(source_domain_id, project_id)).
- `source_domain_workspace_metrics`(source_domain_id, workspace_id, …same…,
  UNIQUE(source_domain_id, workspace_id)).
- `source_domain_metric_history`(source_domain_id, captured_at, counts…) append‑only.
- `domain_authority_results`(domain_key, provider, da, pa, fetched_at, expires_at,
  raw JSONB, UNIQUE(domain_key, provider)) — **global**.
- `domain_authority_history`(domain_key, provider, da, pa, captured_at).
- `semrush_domain_metrics`(domain_key, authority_score, monthly_traffic,
  keywords_count, fetched_at, expires_at, raw JSONB, UNIQUE(domain_key)) — global.
- `semrush_domain_metric_history`(domain_key, authority_score, monthly_traffic,
  keywords_count, captured_at).
- `domain_age_results`(domain_key, created_date, age_days, provider, fetched_at,
  UNIQUE(domain_key)) — global.

**Scoring**
- `scoring_parameters`(key, display_name, value_kind, is_active) — seeded registry.
- `scoring_rule_versions`(id, workspace_id?, scope[global|workspace|project|
  link_type], scope_ref_id?, link_type_id?, version, is_latest, rules JSONB,
  status_thresholds JSONB, created_by, note). *(One versioned table for all scopes —
  `🟦`; the four logical tables `global/workspace/project/link_type_scoring_rules`
  collapse into this `scope` column to avoid duplication; confirm `❓9`.)*

**Google Sheets**
- `google_sheet_connections`(= `sheet_sources`, 1 per project spreadsheet).
- `google_sheet_project_tabs`(sheet_connection_id, gid, tab_name, status,
  UNIQUE(connection, gid)).
- `google_sheet_subsheet_mappings`(tab_id UNIQUE, link_type_id?, import_enabled,
  qa_enabled, is_active, ignored).
- `google_sheet_exports`(report_id, spreadsheet_id, tab, range, exported_at, status).

**Competitor / opportunity**
- `competitor_sheets`(workspace_id, project_id, name, source_kind, spreadsheet_id?/
  upload_key?, column_mapping JSONB, status, soft delete).
- `competitor_sheet_imports`(competitor_sheet_id, status, total/valid/invalid/
  new_domains/existing_domains, error, timestamps).
- `competitor_backlinks`(workspace_id, project_id, competitor_sheet_id,
  canonical_url_id FK, raw_url, source_domain_id FK, anchor?, rel?, link_type_id?,
  link_type_confidence, categorization_source, auto_link_type_id?,
  manual_link_type_id?, index_status?, qa_category).
- `competitor_source_domains`(workspace_id, project_id, competitor_sheet_id?,
  domain_key, url_count, indexed_count, link_type_id?, confidence,
  UNIQUE(ws,project,domain_key)).
- `competitor_domain_comparisons`(workspace_id, project_id,
  competitor_source_domain_id, our_source_domain_id?, category, our_link_count,
  competitor_link_count, our_indexed_pct, da, pa, semrush_as, opportunity_score,
  recommended_action).
- `competitor_link_type_predictions`(competitor_backlink_id, predicted_link_type_id,
  confidence, source).
- `opportunities`(workspace_id, project_id, competitor_domain_comparison_id?,
  source_domain_key, link_type_id?, opportunity_score, status[open|accepted|
  in_progress|done|rejected], created_by).
- `opportunity_assignments`(opportunity_id, user_id, assigned_by, assigned_at).

**Reports / jobs / audit**
- `reports`(+ extends today): `column_set` JSONB, `group_by` JSONB,
  `scoring_rule_version_id?`, `output_target`.
- `report_versions` = existing `version`/`is_latest` (keep).
- `report_snapshots`(report_id, snapshot_blob_key OR rows JSONB) — `🟦` store frozen
  file in object storage (local backend confirmed) keyed here.
- `background_jobs`(id, workspace_id?, type, payload JSONB, status[queued|running|
  done|failed], priority, run_after, attempts, max_attempts, locked_at, locked_by,
  last_error, created_at) — **the Redis‑free queue** (§17).
- `scheduled_jobs`(id, type, cron, payload JSONB, next_run_at, last_run_at,
  is_active) — DB scheduler (replaces RedBeat).
- `delete_audit_logs` / `activity_logs` = existing `audit_logs` (reuse; keep one
  audit table with `action` enum).
- `saved_filters`(workspace_id, user_id?, entity, name, definition JSONB, is_shared)
  — §11A.

---

## 16. Indexing and Large Database Strategy

**The #1 rule:** every duplicate check, filter, sort, and join column is **indexed**.
Without it, a 500K‑row fingerprint scan is ~8–15s; with a B‑tree it's <1ms (your
benchmark is correct — a B‑tree on 500K rows is ~19 comparisons, ~log₂(n), and stays
<2ms at 5M rows). The fingerprint index is the foundation of the whole design.

**Critical indexes (must‑have):**
- `canonical_urls(fingerprint)` **UNIQUE** — the duplicate‑check index.
- `backlinks(canonical_url_id)`, `backlinks(workspace_id)`,
  `backlinks(project_id)`, `backlinks(source_domain_id)`,
  `backlinks(link_type_id)`, `backlinks(assigned_user_id)`, `backlinks(qa_status)`,
  `backlinks(index_status)`, `backlinks(created_at)`, `backlinks(is_duplicate)`,
  `backlinks(conflict_status)`.
- Composite/keyset (existing pattern): `backlinks(project_id, qa_status, score)`,
  `backlinks(project_id, score, id)` (keyset pagination), partial
  `backlinks(project_id, score) WHERE qa_status='FAIL'`.
- Same‑entry unique: partial `UNIQUE(sheet_source_id, tab_id, sheet_row_ref)`.
- `backlink_qa_results(backlink_id, crawled_at)`,
  `backlink_qa_results(scoring_rule_version_id)`.
- `source_domains(domain_key)` UNIQUE‑scoped; `source_domain_project_metrics
  (source_domain_id, project_id)` UNIQUE; `…_workspace_metrics` UNIQUE.
- `domain_authority_results(domain_key, provider)` UNIQUE;
  `domain_authority_results(expires_at)` (refresh due); same for semrush/age.
- `competitor_backlinks(project_id)`, `(canonical_url_id)`, `(source_domain_id)`;
  `competitor_domain_comparisons(workspace_id, project_id, category)`,
  `(opportunity_score)`.
- `backlink_conflict_members(conflict_id)`, `(backlink_id)`;
  `backlink_conflicts(canonical_url_id)`, `(workspace_id, resolution_status)`.
- `background_jobs(status, run_after, priority)` (claim query),
  `background_jobs(locked_at)`; `scheduled_jobs(next_run_at) WHERE is_active`.
- Soft delete hot paths: partial indexes `… WHERE deleted_at IS NULL`.
- GIN on array/JSONB filter columns (e.g. `tags`) — existing pattern.

**Large‑DB practices:**
- **No ratio scans:** index/non‑index ratios read from
  `source_domain_*_metrics.indexed_count/total` (e.g. 7 & 8 → 7/15) — never
  `COUNT(*)` over backlinks. Counters updated transactionally on verdict change +
  nightly reconcile (§11.20).
- **Aggregate tables** for all dashboard metrics; **cursor/keyset pagination** for
  every large grid; avoid `OFFSET` at depth.
- **Partitioning:** keep month partitions on `backlink_qa_results` +
  `backlink_qa_history` (exists, O(1) retention). Partition `competitor_backlinks`
  and the `*_metric_history` tables by month **only if** they reach millions.
- **Normalisation:** canonical URL stored once (not repeated per backlink); metrics
  per domain (not per URL); JSON only for non‑filtered settings/rule bodies.
- **Migrations:** additive, `IF NOT EXISTS`, one per sub‑phase; backfill jobs for
  `canonical_urls`/`source_domains`/counters; reversible downgrades.

---

## 17. Async / Background Job Strategy (Redis‑free)

**Decision required `❓1`.** Two coherent options:

- **Option A — Postgres‑backed queue (🟦 recommended for "no Redis"):**
  - `background_jobs` table; producers `INSERT`; workers claim with
    `SELECT … FROM background_jobs WHERE status='queued' AND run_after<=now()
    ORDER BY priority, id FOR UPDATE SKIP LOCKED LIMIT N` → set `running` →
    process → `done`/`failed` (with `attempts`, exponential `run_after` backoff).
  - `scheduled_jobs` table polled every minute by one leader (advisory lock) to
    enqueue due cron jobs — **replaces RedBeat**.
  - **Pros:** zero Redis; jobs are transactional with data (no dual‑write);
    auditable; survives restarts; scales with `SKIP LOCKED`. **Cons:** ~1s polling
    latency (fine here); we own retry/visibility logic; a real rewrite of the
    current Celery tasks into handlers.
  - Robots cache + per‑domain rate limiter move to small DB tables (or in‑process
    LRU); metric caches become the domain tables themselves.
- **Option B — keep Celery, Redis only as transport, no Redis caching:** least
  work; all caches move to DB; but Redis stays. Not "Redis‑free."

**Job types to model (either option):** crawl_batch, index_check, sheet_sync,
metrics_fetch (moz/semrush/age), competitor_import, competitor_compare,
rescore_project, aggregate_rebuild, report_generate, sheets_export, purge_deleted.
All carry `workspace_id`, are **idempotent**, retry with backoff, isolate
per‑item failures, and log to `activity_logs`. External‑call jobs (metrics, SERP)
are **staggered** + rate‑limited to respect quotas.

---

## 18. API Integration Strategy (Moz, Semrush, domain age)

**Provider abstraction:** extend `integrations/site_metrics.py`'s pattern — a common
interface `fetch(domain) -> MetricResult` per provider, selected by env, so
providers are swappable.

| Provider | Data | Env keys | Notes |
|---|---|---|---|
| **Moz (RapidAPI)** | DA, PA | `RAPIDAPI_KEY`, `MOZ_RAPIDAPI_HOST/ENDPOINT` (exist) | per source main domain |
| **Semrush (RapidAPI)** `NEW` | Authority Score, monthly traffic, # keywords | `SEMRUSH_RAPIDAPI_HOST/ENDPOINT` (+ shared `RAPIDAPI_KEY`) | new provider module |
| **Domain age** `NEW` | created date / age | `DOMAIN_AGE_PROVIDER` + key (whois/RapidAPI) | new provider module |

**Rules (all `✅`):** keys **env‑only** via `config.py` (never hardcoded/committed;
rotate any pasted key); **per‑domain, not per‑URL**; **DB‑cached** with TTL
(`expires_at`) + history; **async background jobs**, staggered; **retry with
backoff**; **graceful degrade** (missing metric → analytics still works, shows
"—"); **cost guardrails** (daily cap per provider, batch limit) `❓8`; **fallback**
provider order configurable. Metrics feed **scoring parameters** (DA/AS/traffic/age
bands) and **competitor opportunity scoring**, and are **filterable/reportable**
(§11A).

---

## 19. Feature-by-Feature Implementation Plan

> Compact entries in your required format. Shared mechanics live in §11A
> (filtration/reports), §12 (canonical/fingerprint), §16 (indexing), §17 (jobs).
> "Files" are real repo paths. Every feature's **Definition of Done includes §11A**
> (its fields appear as filter + facet + group‑by + report column + report filter).

### — Sub‑phase 8.0: Platform —

**FEATURE 38 — Background Jobs Without Redis**
- **GOAL:** replace Redis‑based jobs with a Postgres‑backed queue + scheduler.
- **AREA:** `workers/*`, `celery_app.py`, Redis usage.
- **ROLES:** system.
- **BUSINESS LOGIC:** §17 Option A (`❓1`); idempotent, retry/backoff, `SKIP LOCKED`.
- **USER FLOW:** invisible; admins see a jobs status page.
- **DB:** `background_jobs`, `scheduled_jobs`.
- **BACKEND:** `core/jobs/` (enqueue/claim/scheduler); port tasks → handlers.
- **FRONTEND/UX:** simple "Jobs" admin view (queued/running/failed + retry).
- **FILES:** new `backend/app/core/jobs/*`, rework `backend/app/workers/*`,
  `deploy/ecosystem.config.js` (worker = poller, drop beat/redbeat), `0007`.
- **TASKS:** queue table+claim; scheduler; port each task; jobs UI; load test.
- **TESTING:** concurrent claim no double‑run; retry/backoff; crash recovery;
  scheduler fires once (leader lock); throughput at volume.

**§11A — Dimension Registry (filtration + reports unification)** — see §11A in
`PHASE-8-PLAN.md` (carried forward): one descriptor → filter/facet/group‑by/report
column/report filter/UI. **Build early**; every later feature registers descriptors.

**FEATURE 1 — Multi‑Workspace / Company System**
- **GOAL:** harden multi‑tenant isolation; add workspace switcher + optional company.
- **AREA:** `Workspace`/`WorkspaceMember` (exist), `core/deps.py`, all queries.
- **ROLES:** Admin (workspace/company), all (switch).
- **BUSINESS LOGIC:** §9; workspace = isolation unit; optional `companies` parent.
- **USER FLOW:** switch active workspace; create workspace/company.
- **DB:** `companies?` (`❓6`), `workspaces.company_id?`; ensure every new table has
  `workspace_id`.
- **BACKEND:** `workspace_service`; switcher endpoint; isolation audit.
- **FRONTEND/UX:** workspace switcher in top bar; company grouping.
- **FILES:** `backend/app/services/team_service.py`/new `workspace_service.py`,
  `backend/app/api/v1/auth.py`/`team.py`, `frontend/components/workspace-app.tsx`.
- **TASKS:** switcher; optional company; isolation tests on every endpoint.
- **TESTING:** no cross‑workspace leakage on any query; switch persists; RBAC.

**FEATURE 36 — Audit Logs & History Tracking** — reuse `audit_logs` +
`audit_service.record()`; add `record()` to every new mutation; build an Audit
viewer UI (none today). DB: none. Files: all new services + new `AuditDesk`.
Testing: every mutation logged with before/after; filters; retention.

**FEATURE 35 — Safe Delete & Confirmation System** — soft delete + dependency
preflight + typed confirm + restore + purge job. DB: `deleted_at`/`deleted_by` on
user‑facing tables; reuse `audit_logs`. Backend: `delete_service`. Frontend: shared
`ConfirmDelete` + "Recently deleted". `❓12`. Testing: preflight counts; restore;
purge after window; project archive‑vs‑delete; no stray cascades.

### — Sub‑phase 8.1: Identity core —

**FEATURE 8 — URL Canonicalisation & Fingerprint System**
- **GOAL:** one canonical identity + SHA‑256 fingerprint per URL.
- **AREA:** `normalize.py` (reuse), import, crawl, duplicate, competitor.
- **ROLES:** system.
- **BUSINESS LOGIC:** §12; fingerprint = sha256(canonical); global `canonical_urls`.
- **USER FLOW:** invisible; surfaced via duplicate/conflict views.
- **DB:** `canonical_urls`(fingerprint UNIQUE); `backlinks.canonical_url_id`.
- **BACKEND:** `canonical_service` (canonicalise + upsert); call before every store.
- **FRONTEND/UX:** show canonical URL + fingerprint in link detail.
- **FILES:** new `backend/app/services/canonical_service.py`, new
  `backend/app/models/canonical_url.py`, `import_service.py`, `0008`.
- **TASKS:** canonicaliser+hash; canonical_urls upsert; backfill from existing
  `source_url_normalized`; confirm `❓2`.
- **TESTING:** http/www/slash/utm/case/IDN collapse correctly; fingerprint stable;
  unique index enforced; backfill correctness; <1ms lookup at volume.

**FEATURE 9 — Duplicate & Conflict Detection System**
- **GOAL:** detect same‑fingerprint duplicates; group as conflicts; expose.
- **AREA:** duplicate logic (`link_identity` → superseded), filters/reports.
- **ROLES:** Manager/QA (resolve), all (view).
- **BUSINESS LOGIC:** §13 scenarios + scopes + resolution.
- **USER FLOW:** Conflicts desk → review group → resolve/ignore.
- **DB:** `backlink_conflicts`, `backlink_conflict_members`; `backlinks.
  conflict_status`.
- **BACKEND:** `conflict_service` (detect/group/resolve); migrate off `link_identity`.
- **FRONTEND/UX:** Conflicts desk; conflict badges in grids.
- **FILES:** new `backend/app/services/conflict_service.py`, new
  `backend/app/models/conflict.py`, `0008`, `frontend/.../ConflictsDesk`.
- **TASKS:** detection on insert; scope rules; resolution flow; backfill conflicts.
- **TESTING:** each §13 scenario; scope correctness; no cross‑workspace leak (`❓4`);
  resolution audited; filterable.

**FEATURE 10 — Backlink Import Without Skipping Duplicates**
- **GOAL:** stop skipping; store every row; flag duplicates/conflicts.
- **AREA:** `import_service._process_row` (currently skips/merges).
- **ROLES:** import users.
- **BUSINESS LOGIC:** §13 same‑entry key (`sheet_source_id+tab+row_ref`, `❓3`);
  re‑sync updates in place, distinct rows stored + conflicted.
- **USER FLOW:** sheet sync now shows "N added, M duplicates flagged" (not skipped).
- **DB:** drop `(project,src_norm,tgt_norm)` UNIQUE; add same‑entry partial UNIQUE.
- **BACKEND:** rewrite dedup branch to insert+conflict instead of skip; keep
  per‑sheet‑row idempotency.
- **FRONTEND/UX:** import summary wording; duplicates visible.
- **FILES:** `backend/app/services/import_service.py`,
  `backend/app/services/sheet_sync_service.py`, `0008` (constraint change).
- **TASKS:** same‑entry key; insert‑not‑skip; conflict hookup; migrate constraint.
- **TESTING:** re‑sync no row explosion; genuine dupes stored + flagged; counts
  correct; large import perf.

**FEATURE 26 — Competitor Backlink Fingerprinting** — competitor URLs use the same
`canonical_service` + shared `canonical_urls` (enables exact‑URL match vs ours). DB:
`competitor_backlinks.canonical_url_id`. Files: `competitor_service.py`. Testing:
competitor fp matches our fp for same page; isolation maintained.

### — Sub‑phase 8.2: Foundations —

**FEATURE 2 — Project Settings with Main Domains** — §11.2; `project_settings` +
`project_domains` (1+; one primary); main‑domain matching `❓5`; audited change.
Files: new models + `project_settings_service` + `project_settings.py` API +
SettingsDesk + `0009`. Testing: validation; primary‑unique; matching; history kept.

**FEATURE 3 — User & Employee Code Management** — §11.7; `employee_codes`,
`user_employee_mappings`; reconcile sheet labels → users; `❓10`. Files:
`employee_service`, `team.py`/`users.py`, `0009`, UsersDesk. Testing: uniqueness;
reassignment history; mapping; reports by user/code.

**FEATURE 4 — Google Sheet Main Connection** — reuse `sheet_sources`/main‑sheet
discovery; surface connection config in UI; per‑workspace. Files:
`sheet_sync_service.py`, `sheets.py`, SheetsDesk. Testing: main sheet read; bad URL
handling; SA‑email display.

**FEATURE 5 — Project Sheet & Sub‑Sheet Sync** — §11.4; `google_sheets.
list_worksheets()` (new); `google_sheet_project_tabs` keyed by gid; drift handling.
Files: `integrations/google_sheets.py`, `sheet_tab_service`, `0009`. Testing: detect
tabs; rename via gid; delete→missing (no data loss); legacy single‑tab.

**FEATURE 6 — Link Type Detection from Sub‑Sheets** — tab name → `link_types`
catalog (create/map); inheritance global→workspace→project. DB: `link_types`,
`google_sheet_subsheet_mappings`. Testing: tab→type mapping; unknown→create;
applied to `backlinks.link_type_id`.

**FEATURE 7 — Sub‑Sheet Selection with Checkboxes** — import/QA/active/ignore flags
per tab; sync honours flags. Files: `sheet_tab_service`, `sheet_sync_service`,
SheetsDesk. Testing: unchecked not imported; QA‑off not crawled; toggles re‑sync.

### — Sub‑phase 8.3: Source‑domain intelligence —

**FEATURE 11 — Source Main‑Domain Extraction** — §11.10; reuse
`registrable_domain()` + platform‑host list (`❓7`); `source_domains` +
`backlinks.source_domain_id` (backfill). Files: `source_domain_service`,
`normalize.py`, `0010`. Testing: www/sub collapse; platform hosts; invalid excluded.

**FEATURE 12 — Source Main‑Domain Global Analytics** — workspace/global dashboard
from aggregate tables; new dimension in registry; drill‑down. Files:
`analytics_service`, new `source_domains.py` API, SourceDomainsDesk. Testing: counts
from aggregates (no scan); scope; pagination.

**FEATURE 13 — Source Main‑Domain Project Analytics** — same, project‑scoped via
`source_domain_project_metrics`. Testing: project totals; ratio from counters.

**FEATURE 14 — Aggregate Metrics for Index/Non‑Index Ratios**
- **GOAL:** ratios from stored counts (e.g. 7 indexed/8 not → 7/15), never scans.
- **AREA:** index pipeline, dashboards.
- **BUSINESS LOGIC:** §11.11/§11.20; transactional counter update on verdict change
  + nightly reconcile.
- **DB:** `source_domain_project_metrics`, `source_domain_workspace_metrics`,
  `source_domain_metric_history`.
- **BACKEND:** counter update in index/crawl persist; `aggregate_rebuild` job.
- **FILES:** `source_domain_service`, `workers/...index`, `0010`.
- **TESTING:** counters match facts after random ops; reconcile self‑heals drift;
  ratio math; performance (O(1) read).

**FEATURE 21 — Moz DA/PA via RapidAPI** — §18; reuse provider abstraction; store on
`domain_authority_results` + history; async, cached, env keys. Testing: fetch/cache/
TTL/history; failure non‑blocking; per‑domain not per‑URL.

**FEATURE 22 — Semrush AS/Traffic/Keywords via RapidAPI** — §18; **new** Semrush
provider; `semrush_domain_metrics` + history. Testing: same as 21 + field mapping.

**FEATURE 23 — Domain Age Storage & Refresh** — §18; **new** domain‑age provider;
`domain_age_results`; infrequent refresh. Testing: age computed; cache; fallback.

**FEATURE 15 — Backlink QA Crawl System** *(exists)* — extend only to feed counters
(F14) + versioned scoring (F17). No rebuild.

**FEATURE 16 — Index / Non‑Index Checking System** *(exists)* — extend to update
aggregate counters on verdict change (§11.9). No rebuild.

### — Sub‑phase 8.4: Scoring —

**FEATURE 17 — Dynamic Parameter Scoring** — §11.12; `scoring_parameters` +
weighted model (`❓9`); extractor from artifact+issues+DA/Semrush/age; rule_version
pinned on results; re‑score job. Files: `qa/engine.py`, `qa/scoring.py`, new
`qa/scoring_params.py`, `scoring_rules_service`, `0011`. Testing: deterministic;
normalisation; hard‑fail rules; version pin; old reports unchanged.

**FEATURE 18 — Global Scoring Settings** — `scoring_rule_versions(scope=global/
link_type)`; Admin‑only (`❓`); seed defaults. Testing: defaults apply; versioning.

**FEATURE 19 — Workspace/Project Scoring Overrides** — `scope=workspace|project`;
resolver fallback order. Testing: override precedence; fallback chain.

**FEATURE 20 — Link‑Type‑Based Scoring** — `link_type_id` granularity in rule
resolution. Testing: per‑type scoring; e.g. Web 2.0 nofollow OK, guest post not.

### — Sub‑phase 8.5: Competitor + Reports —

**FEATURE 24 — Competitor / Market Sheet Upload** — §11.13; file or Sheet URL;
`competitor_sheets` + import run; separate storage. Files: `competitor_service`,
`competitors.py`, jobs, `0012`, CompetitorsDesk. Testing: CSV/XLSX/URL; isolation;
multiple per project.

**FEATURE 25 — Competitor Sheet Mapping & Validation** — reuse `import_parse`
auto‑map; require source URL; validation summary. Testing: missing col rejected;
unknown cols preserved.

**FEATURE 27 — Existing vs New Source‑Domain Comparison** — §11.14;
`competitor_domain_comparisons`; fingerprint exact‑URL match (`already_used`). Files:
`competitor_service`, jobs. Testing: existing/new/already_used correctness;
idempotent.

**FEATURE 28 — Auto Link‑Type Categorisation** — §11.15; inherit from our domain
patterns; HIGH/AMBIGUOUS/UNKNOWN; store auto+manual+confidence+source. DB:
`competitor_link_type_predictions`. Testing: single/ambiguous/unknown; override.

**FEATURE 29 — Competitor Link QA Categorisation** — qa_category (existing/new/
exact/opportunity/ambiguous/high‑low value/needs_review) from comparison + metrics.
Testing: each category; thresholds.

**FEATURE 30 — Competitor Opportunity Creation** — promote comparison → `opportunities`
(no auto user creation); approve → assignable. DB: `opportunities`,
`opportunity_assignments`. Testing: no auto users; promote+assign; audit.

**FEATURE 31 — Off‑Page Team Opportunity Dashboard** — board (open→accepted→in
progress→done) + assignment + filters (registry). Testing: transitions; assignment;
perf at volume.

**FEATURE 32 — Reports & Report Versioning** — extend reports: dynamic columns +
group‑by + frozen `report_snapshots` + new report types (source‑domain, competitor,
user‑performance, conflict, metrics). Files: `workers/.../reports.py`,
`report_service`, `0012`. Testing: snapshot immutability; formats; versioning.

**FEATURE 33 — ERP Dashboard Filters** — the full filter set (workspace→opportunity
status→metric ranges) via the §11A registry; connected facets. Testing: every filter;
combined facets; cross‑entity joins.

**FEATURE 34 — Google Sheets Report Export** — §11.18; `write_table`/`create_tab`
(new); `output_target=google_sheet`; never overwrite input cols; confirm
(outward‑facing). DB: `google_sheet_exports`. Testing: tab create/update; chunking;
SA perms; confirm prompt.

**FEATURE 37 — Large DB Indexing & Query Optimisation** — apply §16 indexes; keyset
pagination everywhere; aggregate reads; EXPLAIN‑verified hot queries. Testing:
index‑hit (no seq scans on hot paths); pagination; volume benchmarks.

---

## 20. Testing Strategy

**Framework:** existing `pytest` (87 tests on the server). Keep three layers —
**pure‑logic units** (canonicalisation, fingerprint, scoring, classification — no
DB/network), **service tests** (DB fixtures), **API tests**. **All external calls
(Sheets, Moz, Semrush, domain age, SERP) mocked** — never hit live providers in CI.

**Checklists by area:**
- **Workspace isolation:** every endpoint filters by `workspace_id`; switching;
  no cross‑tenant rows; RBAC per workspace.
- **Project settings / main domain:** validation; primary‑unique; matching (`❓5`);
  history preserved on change.
- **Users / employee codes:** uniqueness (`❓10`); reassignment history; sheet‑label
  reconciliation; reports by user/code.
- **Sheet sync / sub‑sheets:** tab detection (gid‑stable rename, add, delete);
  checkbox import/QA/active; link‑type assignment.
- **Canonicalisation:** http→https, strip www, slash, utm/tracking, case, IDN,
  encoded, invalid → all behave per confirmed `❓2` rules.
- **Fingerprint:** deterministic; collisions impossible (sha256); unique index;
  backfill correctness.
- **Duplicate / conflict:** every §13 scenario; **import does NOT skip**; re‑sync
  idempotent (no row explosion); scopes; resolution; cross‑workspace off (`❓4`).
- **Source domain:** extraction/grouping (`❓7`); aggregate counters correct after
  random insert/delete/verdict‑change; **reconcile self‑heals drift**.
- **Index/non‑index ratio:** from counters only (no scan); math (7/15) exact.
- **Scoring:** deterministic; normalisation; hard‑fail rules; version pin; override
  precedence (project→workspace→link‑type→global); old reports unchanged.
- **Metrics (Moz/Semrush/age):** mocked success/failure/quota; cache hit; TTL
  refresh; history append; per‑domain (not per‑URL); non‑blocking failure;
  cost‑cap respected.
- **Competitor:** upload (file/URL); validation; fingerprint match vs ours;
  existing/new/already_used; auto link‑type (single/ambiguous/unknown + override);
  opportunity create (no auto users) + assign.
- **Reports:** dynamic columns; group‑by; **frozen snapshot immutability**;
  versioning; CSV/XLSX/PDF/Sheets export; SA‑perm errors.
- **Filtration/reports parity (§11A):** every registered dimension filters
  identically in Analytics and Reports; **coverage test** fails CI if a reportable
  field lacks a descriptor.
- **Background jobs:** concurrent claim no double‑run; retry/backoff; crash
  recovery; scheduler fires once; throughput at volume.
- **Delete:** preflight counts; soft delete hides/preserves; restore; purge; audit.
- **Large volume:** seed ~1–2M backlinks → filter/facet/group‑by/report perf;
  index‑hit (no seq scans on hot paths); keyset pagination.

**Gate:** the 87 existing tests stay green at every sub‑phase boundary; run
`venv/bin/pytest -q` on the server before each deploy.

---

## 21. Risk, Security, and Scalability Notes

**Top risks (design‑gated):**
1. **Redis‑free re‑architecture (F38):** replacing Celery is the single biggest
   change. Mitigate: build the Postgres queue behind the existing task interface,
   port one task at a time, run both briefly in parallel, load‑test `SKIP LOCKED`.
   **Confirm `❓1` first.**
2. **Dedup model change (F8–F10):** dropping the unique constraint + storing dupes
   changes row counts and every dedup assumption. Mitigate: additive migration,
   backfill `canonical_urls`/conflicts, same‑entry key to prevent re‑sync explosion,
   extensive tests.
3. **Scoring re‑arch (F17–F20):** changes verdicts. Mitigate: pin rule_version,
   never mutate history, golden‑case tests, feature flag.
4. **Counter drift (F14):** wrong counters = wrong ratios. Mitigate: transactional
   updates + nightly reconcile + a "counters vs facts" test.

**Security (golden rules upheld):**
- All provider keys (Moz, Semrush, domain age, proxy, Sheets SA) **env‑only** via
  `config.py`; never hardcoded/committed; rotate any key pasted in chat. Optional
  runtime config uses the encrypted `settings` table.
- Competitor uploads are **untrusted**: validate, size‑cap; do **not** crawl
  competitor URLs without the **SSRF guard**; treat them as data unless QA is
  explicitly requested.
- Sheets export is **outward‑facing** → explicit confirm; SA least‑privilege.
- Every endpoint behind the right RBAC `Permission`; new perms `MANAGE_SCORING`,
  `MANAGE_COMPETITORS`, `MANAGE_WORKSPACE_SETTINGS`.
- Soft delete + audit = undo + forensics; prod destructive SQL stays gated.
- **No cross‑workspace data leakage** — enforced isolation tests (`❓4`).

**Scalability (1–2M+ backlinks):**
- Fingerprint B‑tree = O(log n) dedup (the foundation). Aggregate tables = O(1)
  ratios. Keyset pagination everywhere. Metrics per domain (not per URL). Month
  partitions on QA history (exists). Competitor + history tables partition‑ready.
- DB‑backed queue scales horizontally with `SKIP LOCKED`; external‑call jobs
  staggered + capped. No Redis to operate/scale.
- Frontend desks split out of the monolith file; data via the registry endpoints.

**Ops:** investigate `api` restarts; one migration per sub‑phase; backfill jobs for
canonical_urls/source_domains/counters; reversible downgrades; `pg_dump`/PITR
backups (DB is the single source of truth).

---

## 22. Final Recommended Roadmap

### 22.1 Best recommended development sequence
**8.0 Platform** (Redis‑free queue, dimension registry, workspace hardening, audit,
safe delete) → **8.1 Identity core** (canonical + fingerprint + conflicts +
no‑skip import) → **8.2 Foundations** (project settings/main domain, users/codes,
sheets/sub‑sheets/link types) → **8.3 Source‑domain intel** (extraction, aggregate
counters, Moz + Semrush + domain age) → **8.4 Scoring** (dynamic, versioned) →
**8.5 Competitor + Reports** (upload→compare→categorise→opportunity→board; ERP
reports + Sheets export).

### 22.2 Minimum Viable Phase (ship first — highest value, controlled risk)
**MVP = 8.0 (cache‑only Redis removal, Option B) + 8.1 (canonical + fingerprint +
store‑don't‑skip duplicates + conflicts) + 8.3 source‑domain analytics with Moz +
Semrush + domain age + aggregate counters.**
Delivers: correct duplicate handling, a true source‑domain intelligence dashboard
with authority/traffic/age, and fast ratios — **without** the full Celery→Postgres
rewrite (defer to a later sub‑phase), the scoring re‑arch, or the competitor engine.
Each piece deploys independently and reversibly.

### 22.3 Full future roadmap (beyond this phase)
- Scheduled report delivery (email/Sheets digest) + alert digest/quiet hours.
- Client portal + read‑only scoped API tokens.
- Trend/time‑series (DA/AS/traffic/indexed% over time); competitor‑gain deltas
  between uploads.
- Full Celery→Postgres queue cutover (if MVP used Option B).
- GitHub remote + one‑command deploy + PITR backups; optional Playwright render pool.

### 22.4 Database Index Checklist (must exist before go‑live)
- [ ] `canonical_urls(fingerprint)` **UNIQUE** ← the duplicate‑check index
- [ ] `backlinks(canonical_url_id)`, `(workspace_id)`, `(project_id)`,
      `(source_domain_id)`, `(link_type_id)`, `(assigned_user_id)`, `(qa_status)`,
      `(index_status)`, `(created_at)`, `(is_duplicate)`, `(conflict_status)`
- [ ] `backlinks(project_id, qa_status, score)` + keyset `(project_id, score, id)`
- [ ] partial `UNIQUE(sheet_source_id, tab_id, sheet_row_ref)` (same‑entry)
- [ ] `backlink_qa_results(backlink_id, crawled_at)`, `(scoring_rule_version_id)`
- [ ] `source_domains(domain_key)`; `source_domain_project_metrics(source_domain_id,
      project_id)` UNIQUE; `…_workspace_metrics` UNIQUE
- [ ] `domain_authority_results(domain_key, provider)` UNIQUE + `(expires_at)`;
      `semrush_domain_metrics(domain_key)` UNIQUE + `(expires_at)`;
      `domain_age_results(domain_key)` UNIQUE
- [ ] `competitor_backlinks(project_id)`, `(canonical_url_id)`, `(source_domain_id)`
- [ ] `competitor_domain_comparisons(workspace_id, project_id, category)`,
      `(opportunity_score)`
- [ ] `backlink_conflicts(canonical_url_id)`, `(workspace_id, resolution_status)`;
      `backlink_conflict_members(conflict_id)`, `(backlink_id)`
- [ ] `background_jobs(status, run_after, priority)`, `(locked_at)`;
      `scheduled_jobs(next_run_at) WHERE is_active`
- [ ] partial `… WHERE deleted_at IS NULL` on soft‑delete hot paths
- [ ] GIN on `tags`/JSONB filter columns
- [ ] `reports(project_id)`, `(workspace_id, report_type) WHERE is_latest`

### 22.5 Questions that MUST be answered before development starts
1. **Redis scope** — cache‑only removal (keep Celery broker) or full Postgres
   queue? (`❓1`)
2. **Canonical rule** — lowercase whole path? drop all params or only tracking?
   always strip trailing slash? (`❓2`)
3. **Same‑entry key** — `sheet_source_id+tab+row_ref` to define "update vs new
   duplicate"? (`❓3`)
4. **Conflict scope** — within workspace/project only, or ever cross‑workspace?
   (`❓4`)
5. **Main domain matching** — replace vs validate per‑row target; one vs many
   primary? (`❓5`)
6. **Company layer** — workspace = company, or a `companies` parent? (`❓6`)
7. **Domain grouping** — collapse Web‑2.0 subdomains or keep per‑subdomain? (`❓7`)
8. **Metrics providers & budget** — confirm Moz + Semrush (RapidAPI endpoints/plans)
   + domain‑age provider + monthly quota/cost caps. (`❓8`)
9. **Scoring model & freeze** — weighted‑parameter vs severity; re‑score history or
   keep frozen? (`❓9`)
10. **Employee codes** — uniqueness; multiple per user; reassignable? (`❓10`)
11. **Sheet layout** — confirm tabs = link types, same columns; sample sheet? (`❓11`)
12. **Delete policy** — entities; restore window; project archive vs delete‑all?
    (`❓12`)
13. **Saved filters/templates scope** — per‑user vs shared workspace? (`❓13`)

---

### Document status
Planning only — **no production code written, nothing implemented, nothing
deployed.** Logic is tagged `✅ CONFIRMED` / `🟦 RECOMMENDED` / `❓ NEEDS
CONFIRMATION`. This master plan supersedes `docs/PHASE-8-PLAN.md` for overlapping
areas and incorporates: canonical/fingerprint identity, store‑don't‑skip
duplicates + conflicts, Moz + Semrush + domain‑age metrics per source domain,
aggregate index/non‑index counters, multi‑workspace/company hardening, Redis‑free
caching + background jobs, and large‑DB indexing. Once the 13 questions above are
answered, **sub‑phase 8.0** can begin (its only hard blocker is `❓1` Redis scope).



