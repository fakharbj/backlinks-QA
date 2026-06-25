# LinkSentinel — Phase 8 Planning Document

> **Scope of this phase:** Project Settings & Main Domain · User/Employee‑Code
> management · Dynamic (global + project + link‑type + parameter) Scoring ·
> Link‑types from Google‑Sheet sub‑sheets · Dynamic safe‑delete · Source
> main‑domain analytics · Competitor/Market analysis · Domain Authority (Moz).
>
> **This is a planning document only. No production code is written here.**
> Where the existing system already does something, this document says so and
> plans to *reuse/extend* it rather than rebuild. Every genuinely undecided
> business rule is tagged **[NEEDS CONFIRMATION]** and collected at the end —
> nothing is guessed.
>
> **Legend used throughout:**
> `✅ CONFIRMED` = derivable from the current code/requirements ·
> `🟦 RECOMMENDED` = my design recommendation where options exist ·
> `❓ NEEDS CONFIRMATION` = a business decision only you can make.

---

## 1. Executive Summary

Phase 8 turns LinkSentinel from a **per‑link QA tool** into a **per‑project,
per‑link‑type, configurable SEO operations platform** with a competitor‑research
arm. It is the largest phase since the original build because it touches the two
deepest subsystems — **scoring** and **Google‑Sheets ingest** — and adds an
entirely new **competitor/opportunity** domain.

The work divides into **five capability clusters**, in dependency order:

1. **Foundations (settings + catalogs).** Project Settings + Project Main
   Domain(s); a real `link_types` catalog; User ↔ Employee‑Code management. These
   are prerequisites for almost everything else.
2. **Dynamic scoring engine.** Global → link‑type → project override resolution,
   versioned rules, frozen scores in reports. This is the highest‑risk item: the
   current engine is **severity‑deduction based**, not weighted‑parameter based,
   so this is a re‑architecture, not a tweak.
3. **Sheet evolution.** Detect sub‑sheets (tabs) inside a project spreadsheet,
   map each tab → link type, choose which tabs sync/QA via checkboxes.
4. **Source‑domain intelligence.** Aggregate source URLs into source main
   domains, attach Domain Authority (reuse the existing Moz/Similarweb
   integration), and surface a source‑domain analytics dashboard.
5. **Competitor/Market analysis.** Upload competitor sheets per project, extract
   their source domains, compare to our existing domains, auto‑categorise link
   types, score opportunities, and produce off‑page opportunity reports.

Cross‑cutting: **dynamic safe‑delete** (soft delete + dependency preflight +
audit), **report snapshots** (true freezing), and **audit/activity logging**
(extend the existing `audit_logs`).

**What already exists and will be reused (not rebuilt):**

| You asked for | Already in the codebase | Plan |
|---|---|---|
| Source main‑domain extraction | `crawler/normalize.py:registrable_domain()` + `BacklinkRecord.source_domain` (registrable, indexed) | **Reuse** the normalizer; add an aggregate table + analytics, do **not** re‑extract |
| Domain Authority via RapidAPI Moz | `integrations/site_metrics.py` (Moz RapidAPI / Moz official / Similarweb, Redis‑cached, provider‑abstracted) | **Reuse** the provider abstraction; move storage from `backlink.extra` to a domain‑keyed table + history |
| Report versioning / "frozen snapshot" | `reports.version` + `is_latest`, `crawl_results.score_breakdown` (frozen per crawl) | **Extend**: add true row‑level report snapshots; clarify freeze semantics |
| Audit logs | `audit_logs` (before/after JSONB) + `audit_service.record()` | **Reuse/extend** for delete + scoring‑change audit |
| Analytics dimensions | `analytics_service.py` whitelist map | **Extend**: add `source_domain` dimension |
| Per‑project sponsored policy | `Project.treat_sponsored_as_follow`, `Project.crawl_settings` (JSONB), `Campaign.campaign_type` | **Generalise** into the dynamic scoring/rules layer |

**Headline risk:** the dynamic scoring engine and the "project main domain = the
target for all links" rule both change **how a verdict is computed**. They must be
designed behind explicit confirmations (Section 3) and shipped with backfill +
re‑scoring jobs, or historical reports will silently shift.

---

## 2. Current Problem Understanding

### 2.1 What the system does today (verified in code)

- **Backlink = the unit.** Each `BacklinkRecord` carries its **own** `target_url`
  / `expected_target_url`; QA link‑matching compares source‑page links against
  *that row's* target (`crawler/engine.py` + `qa/checks/links.py`). The
  **Project's** `target_domain`/`target_urls` exist on the model but are **not**
  the matching authority today.
- **Scoring** (`qa/scoring.py`): `score = 100 − Σ severity.deduction`, clamped,
  then **capped** (CRITICAL caps to 25, CAPTCHA caps to 25). Severity→deduction is
  **hard‑coded in the `Severity` enum** (CRITICAL −60, HIGH −25, MEDIUM −10, LOW
  −3, INFO 0). There is **no per‑parameter weight, no per‑project, no
  per‑link‑type** scoring. `QAPolicy` (`qa/types.py`) has only a handful of
  tunables (`treat_sponsored_as_follow`, `index_expected`, thresholds).
- **Link type** is a **free‑text** column (`BacklinkRecord.link_type`, String 60).
  There is **no `link_types` catalog table**.
- **Google Sheets**: one global main sheet → `Project Name` + `Project Sheet URL`;
  each project sheet is **one `SheetSource` (1:1 with a project), one tab**
  (`SheetSource.sheet_tab`, default = first worksheet). `google_sheets.py` reads a
  single worksheet — there is **no sub‑sheet/tab enumeration** yet.
- **Source domain** is already computed and stored as the **registrable domain**
  (`source_domain`), indexed. There is **no source‑domain aggregate table** and no
  source‑domain analytics page.
- **Domain Authority**: `site_metrics.py` can fetch Moz DA/PA (RapidAPI or
  official) or Similarweb, Redis‑cached per domain, but it's **disabled by
  default** and writes into `backlink.extra['metrics']` — **not** a domain table
  with history.
- **Employee code / assigned user**: free‑text `employee_code` +
  `assigned_user_label` on each backlink, plus an `assignment_history` table. No
  `employee_codes` table, no sheet‑label → app‑user reconciliation.
- **Delete** is **hard delete** (`project_service.delete_project` → `db.delete`,
  relying on FK `ondelete=CASCADE`). No soft delete, no dependency preflight, no
  delete‑specific confirmation logic on the server (only UI).
- **Competitor/market analysis: does not exist.**

### 2.2 What you're missing (your words, mapped to reality)

| You said you lack | Reality | Where this doc solves it |
|---|---|---|
| Proper development sequence | No phased order for these 20 features | §4, §5, §14 |
| Proper business logic | Rules are implicit/contradictory in places | §11 per feature + §3 confirmations |
| Proper database planning | New domains (scoring, competitor) need real schema | §9, §10 |
| Proper feature dependency planning | Scoring depends on link‑types depends on sub‑sheets, etc. | §5 |
| Proper user flow | No flows for settings/competitor/scoring | §11 user‑flow blocks + §8 flowcharts |
| Proper report/dashboard logic | Frozen‑snapshot semantics are only partial today | §11 (F15/F19), §3 (C/Q) |
| Proper scalable structure | Competitor + DA + domain analytics must scale to 1–2M links | §13 |

### 2.3 Existing issues / debt to address during this phase

These were found while reading the code; fixing or consciously accepting each is
part of Phase 8 hygiene:

1. **`backend/app.zip` is tracked in git and shows as modified.** Dead artifact —
   add to `.gitignore` and `git rm --cached`. (Confirmed stale per CLAUDE.md.)
2. **Doc drift on storage:** HANDOFF says `STORAGE_BACKEND=local`, but **MinIO is
   running under PM2 on the server**. Confirm the real prod backend before any
   feature that writes blobs (report snapshots, competitor uploads). `❓`
3. **Dead `qa` Celery queue:** the `qa` queue is declared/routed in
   `celery_app.py` but **no task uses it** (QA runs inline in crawl persistence).
   Either wire async re‑scoring through it (useful for the scoring re‑run job) or
   remove it. Phase 8 will **use it** for the re‑score job (§11 F8).
4. **LinkIdentity rollups** (`occurrence_count`, `project_count`, …) are
   backfilled in migration `0004` but it's unclear they're kept fresh on
   add/delete. Source‑domain rollups (new) must avoid the same trap → use a
   scheduled recompute or triggers (§13).
5. **Alert `digest_mode` + `quiet_hours`** columns exist but enforcement is
   unverified (out of Phase‑8 scope, noted for Phase 9).
6. **"Frozen snapshot" reports aren't fully frozen today:** the report worker
   reads **live** `backlink.score`/status at generation time, not a stored
   row‑level snapshot. The *filters* are frozen; the *data* is current‑as‑of‑run.
   This matters for "how scoring changes affect old reports" (§3 C).
7. **`api` PM2 process shows ~300 restarts** — investigate stability before
   loading it with new heavy endpoints (ops task, §13).
8. **Registrable‑domain grouping is too coarse for Web‑2.0 properties** (e.g.
   `user.blogspot.com` and `other.blogspot.com` both collapse to `blogspot.com`).
   This is a genuine correctness issue for source‑domain analytics and competitor
   grouping — see §3 (E) and §11 (F9). `❓`

---

## 3. Missing Information / Needs Confirmation

> **These block correct implementation. Do not start the dependent feature until
> answered.** Each is restated in the final "Questions" list.

**A. Project Main Domain — cardinality & matching authority.** `❓`
- Feature 1 says "each project should have **a** main domain" (singular); the
  business‑rules section says "each project has **one or more** main domains."
  **Which is it — one, or many?**
- Does the project main domain **replace** each backlink row's `target_url` as the
  match target (i.e. QA = "does the source page link to *any* URL on the project
  main domain?"), or does it **supplement** the per‑row target (validate that each
  row's target is *on* the main domain)? This changes link‑matching, the dedup key
  `(project, source_norm, target_norm)`, and historical data.
- 🟦 **Recommended:** support **many** main domains per project via a
  `project_domains` table (one primary, others secondary), and make matching
  "source links to **any** target URL whose registrable domain ∈ project domains,"
  while still recording the specific matched URL. This is the most flexible and
  backward‑compatible.

**B. Scoring model shape.** `❓`
- Should configurable scoring **replace** the severity‑deduction model, or **layer
  weights on top of it**? Two coherent options:
  - 🟦 **Option B1 (recommended): weighted‑parameter model.** Define a fixed set of
    **scoring parameters** (HTTP status, link found, dofollow, indexed, duplicate,
    DA band, …). Each parameter has a configurable **weight** and a mapping from
    outcome → points. Final score = weighted aggregate, normalised to 0–100. The
    existing 32 QA *checks* still run (they produce issues/evidence), but the
    *score* is computed from the parameter layer. Cleaner mental model for
    non‑technical admins; matches your "parameter scoring" language.
  - **Option B2: keep severity model, make deductions/caps configurable.** Less
    work, but "weights" become "deductions," which is less intuitive and can't
    easily express "Web 2.0 nofollow is fine."
- Does **status** (PASS/WARN/FAIL) derive from the configurable score thresholds,
  or stay on the current classifier? 🟦 Recommended: score bands become
  configurable thresholds per project; the *hard* classifier rules
  (FAIL on 404/dead/link‑missing, REVIEW on CAPTCHA) stay fixed for safety.

**C. Scoring changes vs. old reports (freeze semantics).** `❓`
- When scoring rules change, should historical `crawl_results`/reports be
  **re‑scored**, or remain at the score computed under the rules in effect then?
- 🟦 **Recommended:** **Never silently mutate history.** Each crawl result stores
  the **scoring‑rule version** used. New rules apply going forward; a report
  generated under rule‑version N stores a **frozen row‑level snapshot** (true
  freezing — see §11 F15/F19). Optionally provide an explicit, audited
  "re‑score project under current rules" action that writes **new** crawl results.

**D. Google‑Sheet sub‑sheet layout.** `❓`
- Confirm the real structure: is each **link type a separate tab** inside the
  project spreadsheet (Web 2.0 / Profile / Guest Post …), with the **same column
  layout** in each tab? Or is link type a **column** within a single tab?
- Does the **main sheet** still map Project → one spreadsheet URL (and we read all
  its tabs)? 🟦 Assumed yes.
- A sample project spreadsheet (anonymised) would remove all ambiguity here.

**E. Source‑domain grouping granularity (Web‑2.0 problem).** `❓`
- For platforms like `blogspot.com`, `wordpress.com`, `medium.com`,
  `sites.google.com`, the registrable domain is **shared** across thousands of
  independent properties. Do you want these grouped as **one** source domain
  (`blogspot.com`) or **per‑subdomain/per‑path** (`user.blogspot.com`)?
- 🟦 **Recommended:** maintain a small **"platform host" list** (PSL private
  domains) for which we group by **full host** (or host+first path segment for
  `medium.com/@user`) instead of registrable domain. Otherwise Web‑2.0 analytics
  and competitor opportunity counts will be meaningless.

**F. Employee‑code rules.** `❓`
- Is `employee_code` **unique per workspace**? Can one user hold **multiple**
  codes over time? Can a code be **reassigned** to a different user?
- 🟦 **Recommended:** code unique per workspace at a point in time; full history
  kept; reassignment allowed and audited.

**G. Domain Authority provider & budget.** `❓`
- Confirm exact provider: `moz_rapidapi`, `moz_official`, or `similarweb`
  (all already supported in `site_metrics.py`). What's the **monthly quota /
  cost ceiling**? This drives batch size, cache TTL, and refresh cadence.

**H. Competitor sheet format & source.** `❓`
- What columns do competitor sheets contain (just source URLs? source+anchor?
  target? DA?)? Are they **uploaded files** (CSV/XLSX) or **Google Sheets URLs**
  like project sheets? 🟦 Recommended: support both, reuse the existing import
  pipeline; treat unknown columns leniently.

**I. Soft‑delete scope & restore window.** `❓`
- Which entities get **soft delete** (recoverable) vs **hard delete**? Is there a
  **restore window** (e.g. 30 days) after which a purge job hard‑deletes?
- 🟦 **Recommended:** soft‑delete projects, sheets, competitor data, scoring rules,
  users; hard‑delete only trivial join rows. 30‑day restore, then audited purge.

**J. Who may edit global scoring?** `❓` 🟦 Recommended: **Admin only** for global
rules; **Manager+** for project overrides (new permissions in §11 F4).

---

## 4. Recommended Development Sequence (high level)

Build in five sub‑phases (8.1 → 8.5). Each is independently shippable and leaves
the system green. **Do not parallelise across a dependency edge (see §5).**

| Sub‑phase | Theme | Features | Why first/last |
|---|---|---|---|
| **8.1 Foundations** | Catalogs & settings | F1 Project Settings + Main Domain · F2 Users/Employee Codes · F20 Audit/History scaffolding · F7 Safe‑delete framework | Everything else references link‑types, domains, users, audit |
| **8.2 Link‑type & Sheets** | Sheet evolution | F5 Sub‑sheet detection · F6 Tab selection checkboxes · (link‑types catalog finalised) | Scoring & competitor categorisation need a real link‑type catalog |
| **8.3 Scoring** | Dynamic scoring | F4 Global scoring · F3 Project scoring · F8 Dynamic parameter scoring · (versioning + freeze) | Highest risk; depends on link‑types (8.2); gates report changes |
| **8.4 Source‑domain intel** | Aggregation + DA | F9 Source‑domain extraction/aggregate · F16 DA via Moz · F10 Source‑domain analytics dashboard | Feeds competitor comparison & opportunity scoring |
| **8.5 Competitor/Market** | Opportunity engine | F11 Upload · F12 Mapping/validation · F13 Existing‑vs‑new comparison · F14 Auto link‑type categorisation · F17 Competitor QA categorisation · F15 Opportunity reports · F18 Off‑page dashboard · F19 Sheets export | Depends on link‑types, source domains, DA |

**Minimum Viable Phase (MVP)** = **8.1 + 8.2 + the read‑only half of 8.4** (source
main‑domain analytics using DA you already can fetch). This delivers immediate
value (project settings, real link types, source‑domain dashboard) **without** the
risky scoring re‑architecture or the large competitor subsystem. (See §14.)

---

## 5. Feature Dependencies

```
                         ┌─────────────────────────────┐
                         │ F20 Audit/Activity logging   │  (extend audit_logs; needed by all deletes/edits)
                         └──────────────┬──────────────┘
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        ▼                               ▼                                ▼
┌────────────────┐         ┌────────────────────────┐        ┌────────────────────┐
│ F1 Project      │         │ F2 Users / Employee     │        │ F7 Safe‑delete      │
│ Settings +      │         │ Codes + mapping         │        │ framework (soft     │
│ Main Domain(s)  │         │                         │        │ delete + preflight) │
└───────┬────────┘         └───────────┬────────────┘        └─────────┬──────────┘
        │                              │                                │
        │                              │                                │ (used by every delete)
        ▼                              │                                │
┌────────────────────────┐            │                                │
│ link_types CATALOG      │◄───────────┘ (employee/user used in reports)│
│ (F5/F6 populate it)     │                                             │
└───────┬─────────────────┘                                            │
        │                                                              │
        ▼                                                              │
┌────────────────────────┐   ┌──────────────────────────┐             │
│ F5 Sub‑sheet detection  │──►│ F6 Tab→link‑type select   │             │
└───────┬─────────────────┘   └─────────────┬────────────┘             │
        │                                    │                          │
        ▼                                    ▼                          │
┌──────────────────────────────────────────────────────┐              │
│ F4 Global scoring → F3 Project scoring → F8 Parameter  │              │
│ scoring (resolution: global→link‑type→project; versioned)             │
└───────┬────────────────────────────────────────────────┘             │
        │ (score feeds reports + analytics)                             │
        ▼                                                               │
┌────────────────────────┐   ┌──────────────────────────┐              │
│ F9 Source main‑domain   │──►│ F16 Domain Authority (Moz)│              │
│ aggregate (reuse norm)  │   └─────────────┬────────────┘              │
└───────┬─────────────────┘                 │                          │
        ▼                                    ▼                          │
┌────────────────────────┐                                              │
│ F10 Source‑domain        │                                            │
│ analytics dashboard      │                                            │
└───────┬──────────────────┘                                           │
        ▼                                                               │
┌───────────────────────────────────────────────────────────────────┐ │
│ COMPETITOR SUBSYSTEM (needs link_types, source_domains, DA, delete) │◄┘
│ F11 Upload → F12 Map/validate → F13 Existing‑vs‑new → F14 Auto link  │
│ ‑type → F17 QA categorisation → F15 Opportunity reports →            │
│ F18 Off‑page dashboard → F19 Sheets export                            │
└───────────────────────────────────────────────────────────────────┘
```

**Hard edges (must respect):**
- F3/F4/F8 (scoring) **require** the `link_types` catalog (from F5/F6) — you can't
  set "Web 2.0 scoring" before "Web 2.0" exists as a typed entity.
- F13/F14 (competitor comparison & auto‑categorisation) **require** F9
  (source‑domain aggregate) and the link‑type catalog.
- F16 (DA) **feeds** F10 and F13/F15 but can ship independently (degrade
  gracefully when DA is absent).
- Every delete feature **requires** F7 + F20.

---

## 6. Full System Architecture Plan

Phase 8 keeps the existing **modular monolith** shape (FastAPI API + Celery
workers sharing models/services/config). No new services/processes are required.

### 6.1 New backend modules (following the existing layering)

```
backend/app/
├── api/v1/
│   ├── project_settings.py     (NEW) project settings + main domains
│   ├── users.py                (NEW) user/employee-code admin (or extend team.py)
│   ├── scoring.py              (NEW) global/project/link-type scoring rules
│   ├── link_types.py           (NEW) link-type catalog + sub-sheet mapping
│   ├── sheets.py               (EXTEND) sub-sheet enumeration + tab selection
│   ├── source_domains.py       (NEW) source-domain analytics
│   ├── competitors.py          (NEW) competitor sheets, comparison, opportunities
│   └── deletes.py              (NEW, or per-router) delete-preflight + soft delete
├── services/
│   ├── project_settings_service.py  (NEW)
│   ├── employee_service.py          (NEW) user↔code mapping + reconciliation
│   ├── scoring_rules_service.py     (NEW) rule CRUD + versioning + resolution
│   ├── link_type_service.py         (NEW) catalog + tab mapping
│   ├── sheet_tab_service.py         (NEW) sub-sheet detect/select/sync
│   ├── source_domain_service.py     (NEW) aggregate rollups + analytics
│   ├── domain_authority_service.py  (NEW) wraps integrations/site_metrics
│   ├── competitor_service.py        (NEW) upload, comparison, opportunity scoring
│   └── delete_service.py            (NEW) soft delete + dependency preflight + restore
├── qa/
│   └── scoring.py              (EXTEND/REPLACE) parameter-weight resolution (Option B1)
│   └── scoring_params.py       (NEW) canonical parameter registry + outcome→points
├── workers/tasks/
│   ├── scoring.py              (NEW) re-score project under current rules (uses `qa` queue)
│   ├── domain_authority.py     (NEW) batched DA fetch/refresh (uses index.check-style stagger)
│   ├── competitors.py          (NEW) import + comparison + categorisation jobs
│   └── source_domains.py       (NEW) periodic rollup recompute
└── models/  (NEW model files — see §10)
```

### 6.2 New queues / beat jobs

- Reuse `qa` queue for **re‑score** jobs (it's currently dead — §2.3).
- Reuse pattern of `index.check` (staggered external calls) for **DA fetch**;
  route `tasks.domain_authority.*` and `tasks.competitors.*` to existing
  `index.check`/`sheets.sync`/`default` or add `domain.authority` +
  `competitors` queues. 🟦 Recommended: add two queues to keep heavy external
  calls isolated.
- New beat jobs: `recompute-source-domain-rollups` (daily), `refresh-domain-
  authority-due` (daily, respects cache TTL), optionally `purge-soft-deleted`
  (daily, after restore window).

### 6.3 Frontend

All UI continues to live in `frontend/components/workspace-app.tsx` (one tree) +
`frontend/lib/api.ts`. New **desks/tabs**:
- **Settings desk** (Project Settings, Main Domains, Scoring, Link‑types, Sub‑sheet
  selection, Global scoring — Admin/Manager scoped).
- **Source Domains desk** (analytics).
- **Competitors desk** (upload, comparison, opportunities, off‑page workflow).
- Delete confirmation modals become a shared component (`ConfirmDelete` with
  dependency preview).

> Note: `workspace-app.tsx` is already ~2,210 lines. 🟦 Recommended hygiene: split
> the new desks into sibling files (`components/desks/*.tsx`) imported by the tree,
> rather than growing the single file. This is a *structure* improvement, not a
> behaviour change, and keeps Phase 8 maintainable.

---

## 7. Data Flow Plan

### 7.1 Settings & catalog flow
`Admin edits Project Settings → project_settings + project_domains rows →
re‑match/re‑score job (optional, audited) → analytics & reports read new domains.`

### 7.2 Sheet → link‑type flow
`Sheets sync → enumerate tabs → upsert google_sheet_project_tabs → admin selects
which tabs import/QA (checkboxes) + maps tab→link_type → per‑tab import via
existing import pipeline → backlink_records.link_type set from tab mapping.`

### 7.3 Scoring flow (Option B1)
`Crawl → QA checks produce issues/evidence (unchanged) → parameter extractor maps
artifact+issues → parameter outcomes → scoring resolver picks the effective rule
set (project override → link‑type rule → global default) at version V →
weighted score + band → stored on crawl_results WITH rule_version=V → denormalised
to backlink_records.`

### 7.4 Source‑domain flow
`Backlink upsert → source_domain (registrable/platform host) computed → upsert
source_domains aggregate (counts, %s) via scheduled recompute → DA fetched per
source domain (cached) → analytics dashboard reads aggregate + DA.`

### 7.5 Competitor flow
`Upload competitor sheet → competitor_sheets + competitor_sheet_imports →
parse+normalize → competitor_backlinks + competitor_source_domains →
compare competitor domains vs project source_domains → competitor_domain_comparisons
(existing/new) → auto link‑type categorisation (inherit from our domain patterns) →
opportunity scoring (DA + index + gap) → opportunity report → optional export to
Google Sheet.`

---

## 8. Flowchart‑Style Logic

### 8.1 Project settings creation / update
```
START
→ Admin/Manager opens Project → Settings
→ Loads current settings + project_domains (primary + secondary)
→ User edits name / main domain(s) / scoring profile / schedule / policy flags
→ Validate: at least one domain; each domain is a valid registrable domain;
            no duplicate domain across THIS project; warn if domain already used
            by another project in the workspace
→ IF main domain changed:
    → Record old → new in audit_logs (before/after)
    → Ask: "Re-match & re-score existing links under the new domain now?"  [NEEDS CONFIRMATION A]
        → IF yes → enqueue tasks.scoring.rescore_project (background, audited)
        → IF no  → keep historical verdicts; new domain applies to future crawls
    → Keep OLD QA history linked to the crawl that produced it (history is immutable)
→ Persist project_settings + project_domains
→ Invalidate analytics caches for the project
→ END
```

### 8.2 Google‑Sheet sub‑sheet / link‑type sync
```
START
→ Sheets sync triggered (manual or scheduled) for a project spreadsheet
→ google_sheets.list_worksheets(spreadsheet_id)   (NEW integration fn)
→ FOR each tab:
    → Upsert google_sheet_project_tabs(tab_name, gid, last_seen_at, status=detected)
    → IF tab is new and unmapped → status=needs_mapping (do NOT import yet)
→ Admin opens Sub-sheet selection:
    → For each tab: checkbox [import?] [QA?] [active?] + dropdown [map → link_type]
    → "Other"/unknown tab → create link_type or mark ignored
→ Save selections → google_sheet_subsheet_mappings
→ FOR each tab WHERE import=true AND active=true:
    → read_project_sheet(spreadsheet_id, tab) → existing import pipeline
    → set backlink_records.link_type = mapped link_type
→ Handle drift:
    → tab RENAMED → match by gid (stable id) not name; update tab_name; keep mapping
    → tab DELETED → mark mapping status=missing; do NOT delete imported links;
                    surface a warning to admin
    → tab ADDED   → status=needs_mapping; surface for admin decision
→ END
```

### 8.3 User & employee‑code mapping
```
START
→ Admin opens Users / Employee Codes
→ Manual: add user / edit user / assign code / update code / set active|inactive
→ Validate code uniqueness per workspace  [NEEDS CONFIRMATION F]
→ Sheet reconciliation:
    → Collect distinct (assigned_user_label, employee_code) seen in backlinks
    → FOR each distinct label:
        → IF exact mapping exists in user_employee_mappings → link to app user
        → ELSE IF code matches a known employee_code → suggest that user
        → ELSE → mark UNMAPPED, present to admin for manual mapping
    → Admin confirms/overrides mappings
→ On mapping change: record in audit_logs; (optionally) backfill
  backlink_records.assigned_user_id for matching labels
→ Reports/analytics by user can now use app-user identity OR raw sheet label
→ END
```

### 8.4 Scoring calculation (Option B1, recommended)
```
START (a crawl artifact + its QA issues are ready)
→ Determine link_type of the backlink (from tab mapping or free text)
→ Resolve effective scoring rule set:
    → IF project_scoring_rules exist for (project, link_type)     → use them
    → ELSE IF project_scoring_rules exist for (project, ANY)      → use them
    → ELSE IF link_type_scoring_rules exist for link_type (global)→ use them
    → ELSE                                                        → global_scoring_rules (defaults)
    → Capture the chosen scoring_rule_version = V
→ Extract parameter outcomes from artifact+issues:
    (http_ok?, link_found?, target_match?, dofollow?, indexed?, duplicate?,
     da_band, robots_ok?, canonical_ok?, crawl_ok?, assigned?)
→ score = Σ (parameter.weight × outcome_points(parameter))   normalised → 0..100
→ Apply HARD safety rules (unchanged, non-configurable):
    → link missing / 404 / dead / cross-domain canonical → FAIL regardless
    → CAPTCHA / WAF uncertainty → NEEDS_MANUAL_REVIEW
→ Determine status from configurable bands (fail<X, warn<Y, else pass)
→ Persist score + band + breakdown + rule_version=V on crawl_results
→ Denormalise to backlink_records (score/status/top_issue)
→ END
```

### 8.5 Source main‑domain extraction
```
START (backlink source_page_url)
→ normalize_url(source_page_url)  → NormalizedUrl (existing)
→ IF host registrable domain ∈ PLATFORM_HOST_LIST (blogspot/wordpress/medium/...)  [NEEDS CONFIRMATION E]
    → source_domain_key = full host (or host + first path segment for medium/@user)
→ ELSE
    → source_domain_key = registrable_domain (existing behaviour)
→ Upsert source_domains(workspace_id, domain_key) ; bump counters
→ Link backlink_records.source_domain_id → source_domains.id (new FK)
→ END
```

### 8.6 Competitor sheet upload
```
START
→ User selects project → Competitors → Upload
→ Choose source: file (CSV/XLSX) OR Google Sheet URL
→ Create competitor_sheets row + competitor_sheet_imports (status=pending)
→ Validate: at least a source URL column; map columns (reuse import auto-map)
→ Stage rows → normalize source URLs (reuse normalize_url)
→ Drop invalid/unsupported-scheme URLs (record count)
→ Extract competitor source main domains (same logic as 8.5)
→ Persist competitor_backlinks + competitor_source_domains (SEPARATE from project links)
→ Enqueue comparison job (8.7) + DA fetch for new domains (8.9)
→ END
```

### 8.7 Existing vs new source‑domain comparison
```
START (competitor_source_domains for a project)
→ Load project's existing source_domains set (from our backlinks)
→ FOR each competitor source domain D:
    → IF D ∈ existing project source domains:
        → category = EXISTING
        → attach: our backlinks count from D, competitor count from D,
                  indexed%, link_type(s) we use for D, avg score, DA, users
        → IF we have FEW links from a HIGH-DA existing domain → flag "expand here"
    → ELSE:
        → category = NEW_OPPORTUNITY
        → attach: competitor URLs, estimated link type (8.8), DA, indexed%
→ Write competitor_domain_comparisons (category + metrics + recommended_action)
→ END
```

### 8.8 Auto link‑type categorisation
```
START (a competitor source domain D, not yet typed)
→ Look up how OUR project uses domain D (from our backlinks' link_type):
    → IF D unseen in our data → link_type = UNKNOWN/NEW ; confidence = none
    → ELSE collect distinct link_types used for D:
        → IF exactly ONE link_type → assign it ; confidence = HIGH ; source = inherited_single
        → IF MULTIPLE link_types  → mark AMBIGUOUS ; store candidates ; confidence = LOW
→ Allow manual override (records source = manual, confidence = confirmed)
→ Persist link_type + confidence + categorization_source on competitor_backlinks
→ Uncategorised/ambiguous → surfaced in off-page review queue
→ END
```

### 8.9 Domain authority checking
```
START (a set of source/competitor domains needing DA)
→ FOR each domain (deduped by domain_key):
    → IF domain_authority_results fresh within cache TTL → use cached  [NEEDS CONFIRMATION G]
    → ELSE enqueue tasks.domain_authority.fetch_one(domain) with stagger
→ fetch_one:
    → call integrations.site_metrics (Moz RapidAPI / official / Similarweb) — EXISTING
    → on success → upsert domain_authority_results (current) + append domain_authority_history
    → on failure/quota → mark stale, DO NOT block analytics; retry with backoff
→ source_domains.da_* denormalised from latest domain_authority_results
→ END
```

### 8.10 Competitor opportunity report generation
```
START
→ Select project + scope (new only | existing | all) + min DA + link types
→ Pull competitor_domain_comparisons + DA + index status
→ Opportunity score = f(DA band, indexed%, our_gap (we have 0 or few links),
                        link_type value weight, competitor frequency)
→ Rank; group by EXISTING vs NEW
→ Render (reuse report worker: CSV/XLSX/PDF) as a FROZEN snapshot (rule_version + data)
→ Optional: export to a Google Sheet tab (reuse write_back pattern)  [NEEDS CONFIRMATION H]
→ END
```

### 8.11 Safe delete confirmation flow
```
START
→ User clicks Delete on entity E (project/sheet/tab-mapping/user/employee-code/
                                  scoring-rule/imported-links/competitor-sheet/market-data)
→ delete_service.preflight(E): count dependents
    (e.g. project → N backlinks, M crawl_results, K reports, J competitor sheets)
→ Show confirmation modal:
    → list dependent counts + "what happens to each" (cascade vs detach vs keep)
    → IF project delete → ask: delete links+history too? or archive project & keep history?  [NEEDS CONFIRMATION A/I]
    → require typing the entity name for high-impact deletes
→ On confirm:
    → SOFT delete: set deleted_at + deleted_by; exclude from normal queries
    → write audit_logs (action=DELETE, before snapshot, dependent counts)
    → DO NOT physically remove within restore window
→ Restore path: clear deleted_at (audited) within window
→ Purge job: after restore window, hard-delete (cascade) — audited
→ END
```

---

## 9. Database Relationship Planning (before final schema)

### 9.1 Main entities (new vs existing)

**Existing, reused/extended:** `workspaces`, `users`, `workspace_members`,
`projects`, `project_members`, `vendors`, `campaigns`, `backlink_records`,
`crawl_results` (partitioned), `backlink_history` (partitioned), `backlink_issues`,
`reports`, `sheet_sources`, `imports`/`import_rows`, `link_identity`,
`assignment_history`, `index_checks`, `audit_logs`, `settings`.

**New in Phase 8:** `project_settings`, `project_domains`, `link_types`,
`employee_codes`, `user_employee_mappings`, `global_scoring_rules`,
`link_type_scoring_rules`, `project_scoring_rules`, `scoring_parameters`,
`scoring_rule_versions`, `google_sheet_project_tabs`,
`google_sheet_subsheet_mappings`, `source_domains`, `source_domain_metrics`
(= DA cache, see merge note), `domain_authority_results`,
`domain_authority_history`, `competitor_sheets`, `competitor_sheet_imports`,
`competitor_backlinks`, `competitor_source_domains`,
`competitor_domain_comparisons`, `report_snapshots`.

### 9.2 Reconciliation of your proposed table list ↔ reality

| Your proposed table | Status | Decision |
|---|---|---|
| projects | exists | extend (soft‑delete cols) |
| project_settings | new | **new** (1:1 project) — typed columns + JSONB overflow |
| project_domains | new | **new** (1 project → N domains, one `is_primary`) |
| users | exists (`users`) | extend (no change to auth) |
| employee_codes | new | **new** |
| user_employee_mappings | new | **new** (M:N user↔code over time + sheet‑label aliases) |
| link_types | new | **new** catalog (workspace‑scoped; global + per‑project enable) |
| global_scoring_rules | new | **new** |
| project_scoring_rules | new | **new** |
| link_type_scoring_rules | new | **new** |
| scoring_rule_versions | new | **new** (immutable snapshots of a rule set) |
| google_sheet_connections | exists as `sheet_sources` | **reuse** (rename concept, not table) |
| google_sheet_project_tabs | new | **new** (1 sheet_source → N tabs) |
| google_sheet_subsheet_mappings | new | **new** (tab → link_type + import/QA flags) |
| backlinks | exists as `backlink_records` | extend (`source_domain_id`, soft‑delete) |
| backlink_assignments | partial (`assignment_history`) | **reuse**; add code linkage |
| backlink_qa_results | exists as `crawl_results` | extend (`scoring_rule_version_id`) |
| backlink_qa_history | exists as `backlink_history` | reuse (immutable) |
| source_domains | new (string exists on backlink) | **new** aggregate table |
| source_domain_metrics | new | **merge** with `domain_authority_results` (one DA table) 🟦 |
| competitor_sheets | new | **new** |
| competitor_sheet_imports | new | **new** (or reuse `imports` with a `kind` flag) 🟦 |
| competitor_backlinks | new | **new** (separate from `backlink_records`) |
| competitor_source_domains | new | **new** |
| competitor_domain_comparisons | new | **new** |
| domain_authority_results | new | **new** (current DA per domain) |
| domain_authority_history | new | **new** (append‑only DA over time) |
| reports | exists | extend |
| report_versions | exists (`reports.version`/`is_latest`) | **reuse** |
| report_snapshots | new | **new** (true frozen row‑level data) |
| delete_audit_logs | exists as `audit_logs` | **reuse** (action=DELETE) |
| activity_logs | exists as `audit_logs` | **reuse** |
| background_jobs | partial (`crawl_jobs` + Celery) | 🟦 add generic `async_jobs` for non‑crawl jobs OR reuse `crawl_jobs` generalised |

> 🟦 **Recommendation:** collapse `source_domain_metrics` + `domain_authority_
> results` into **one** `domain_authority_results` table (current value) plus
> `domain_authority_history` (append‑only). Two tables for "current DA" would
> duplicate state and risk drift.

### 9.3 Relationship notes

- **project → project_domains**: 1‑to‑N, exactly one `is_primary=true` enforced by
  a partial unique index `(project_id) WHERE is_primary`.
- **link_types**: workspace‑scoped catalog. `global` flag = available to all
  projects; per‑project enablement via `project_settings`/junction (🟦 keep simple:
  link_types are workspace catalog, projects reference by id).
- **scoring resolution is a 3‑level fallback** (project → link‑type → global), each
  level pointing at an immutable `scoring_rule_versions` row. `crawl_results` stores
  the **version id actually used** (FK), giving perfect auditability and answering
  "how scoring changes affect old reports" (they don't — old results keep their
  version).
- **source_domains** is an **aggregate/rollup** keyed by `(workspace_id,
  domain_key)`; `backlink_records.source_domain_id` FK links each link to it.
  Competitor side has its own `competitor_source_domains` to keep competitor data
  **physically separate** from our verified data.
- **competitor_domain_comparisons** is the M:N bridge insight between
  `competitor_source_domains` and our `source_domains` (category + metrics).
- **M:N relationships:** user↔employee_code (history), link_type↔project (enable),
  competitor_domain↔our_domain (comparison). All via explicit junction tables (no
  raw arrays for relational data).
- **History/versioning:** scoring rules (versioned), DA (history table), QA
  (existing partitioned history), reports (version + new snapshots), audit (all
  mutations).
- **Soft delete:** add `deleted_at TIMESTAMPTZ NULL`, `deleted_by UUID NULL` to
  soft‑deletable tables; all default queries filter `deleted_at IS NULL`.

---

## 10. Final Recommended Database Structure

> Migrations continue from `0006` → `0007`, `0008`, … (one per sub‑phase to keep
> them reviewable). All new tables: `workspace_id` FK (tenant scope),
> `UUIDPrimaryKeyMixin` + `TimestampMixin`, native enums via `pg_enum`, JSONB for
> flexible bags — **matching existing conventions**. Types below are indicative.

### 10.1 Foundations (migration 0007)

**`project_settings`** (1:1 with project)
- `project_id` UUID FK→projects (unique), `workspace_id` UUID FK
- `default_link_type_id` UUID FK→link_types NULL
- `scoring_profile` String — `inherit_global | custom`
- `index_expected` bool, `treat_sponsored_as_follow` bool (migrate from project)
- `status_thresholds` JSONB (`{fail:<30, warn:<80}`) — configurable bands
- `extra` JSONB
- *Index:* unique(project_id)

**`project_domains`** (1 project → N)
- `id`, `workspace_id`, `project_id` FK
- `domain` String(255) (registrable or platform host), `host_pattern` String NULL
- `is_primary` bool
- `deleted_at`, `deleted_by`
- *Constraints:* unique(`project_id`,`domain`); partial unique(`project_id`) WHERE
  `is_primary`; index(`workspace_id`,`domain`)

**`link_types`** (workspace catalog)
- `id`, `workspace_id`, `name` String(60), `slug`, `is_global` bool,
  `is_active` bool, `description`, `default_value_weight` int (for opportunity
  scoring), `deleted_at`,`deleted_by`
- *Constraints:* unique(`workspace_id`,`slug`)
- **Backfill:** seed from existing distinct `backlink_records.link_type` values.

**`employee_codes`**
- `id`, `workspace_id`, `code` String(60), `label` String NULL, `is_active` bool,
  `deleted_at`,`deleted_by`
- *Constraints:* unique(`workspace_id`,`code`) `❓F`

**`user_employee_mappings`** (user ↔ code ↔ sheet label, with history)
- `id`, `workspace_id`, `user_id` UUID FK→users NULL (NULL = external/unmapped),
  `employee_code_id` UUID FK→employee_codes NULL,
  `sheet_user_label` String(200) NULL, `is_current` bool,
  `effective_from` timestamptz, `effective_to` timestamptz NULL,
  `created_by` UUID
- *Index:* (`workspace_id`,`sheet_user_label`), (`employee_code_id`),
  partial unique(`workspace_id`,`employee_code_id`) WHERE `is_current`

**Soft‑delete columns** added to: `projects`, `sheet_sources`, `link_types`,
`employee_codes`, `scoring` tables, competitor tables, `backlink_records`
(optional). (`deleted_at`, `deleted_by`.)

### 10.2 Sheets / link‑type mapping (migration 0008)

**`google_sheet_project_tabs`** (1 sheet_source → N tabs)
- `id`, `workspace_id`, `sheet_source_id` FK→sheet_sources, `gid` String (stable
  tab id), `tab_name` String(200), `status` enum(`detected|mapped|needs_mapping|
  missing|ignored`), `last_seen_at`, `row_count` int
- *Constraints:* unique(`sheet_source_id`,`gid`); index(`sheet_source_id`)
- > **Schema change to `sheet_sources`:** the current
  `uq_sheet_sources_project` (one SheetSource per project) and the per‑tab unique
  must be reconciled. 🟦 Keep `sheet_sources` = 1 per project (the spreadsheet);
  move per‑tab state into `google_sheet_project_tabs`. The existing
  `(workspace,spreadsheet,sheet_tab)` unique becomes redundant → drop or relax.

**`google_sheet_subsheet_mappings`** (tab → link type + flags)
- `id`, `workspace_id`, `tab_id` FK→google_sheet_project_tabs (unique),
  `link_type_id` FK→link_types NULL, `import_enabled` bool, `qa_enabled` bool,
  `is_active` bool, `ignored` bool, `created_by`
- *Constraints:* unique(`tab_id`)

### 10.3 Scoring (migration 0009)

**`scoring_parameters`** (canonical parameter registry — seeded, rarely changes)
- `id`, `key` String (e.g. `http_status`,`link_found`,`dofollow`,`indexed`,
  `duplicate`,`domain_authority`,`robots`,`canonical`,`crawl_success`,`assigned`),
  `display_name`, `category`, `value_kind` enum(`boolean|enum|numeric_band`),
  `is_active`
- *Constraints:* unique(`key`). **Workspace‑agnostic** (shared registry).

**`scoring_rule_versions`** (immutable snapshot of a complete rule set)
- `id`, `workspace_id`, `scope` enum(`global|link_type|project`),
  `scope_ref_id` UUID NULL (link_type_id or project_id; NULL for global),
  `link_type_id` UUID NULL (for project+link_type granularity),
  `version` int, `is_latest` bool, `rules` JSONB (the full
  parameter→weight/outcome map, frozen), `status_thresholds` JSONB,
  `created_by`, `note`
- *Constraints:* index(`workspace_id`,`scope`,`scope_ref_id`,`link_type_id`)
  WHERE `is_latest`
- > 🟦 **Recommendation:** model *all three levels* (global/link‑type/project) as
  rows in **one** `scoring_rule_versions` table distinguished by `scope`, rather
  than three near‑identical tables (`global_scoring_rules`,
  `link_type_scoring_rules`, `project_scoring_rules`). This removes duplication and
  makes the resolver a single query. (Your three proposed tables are presented as
  the *logical* concept; the *physical* recommendation is one versioned table — see
  §3 confirmations if you prefer three.)

If you prefer the explicit three‑table form, the columns mirror the above per
scope; either way each must carry `version`/`is_latest`/`rules` JSONB.

**`crawl_results`** (extend): add `scoring_rule_version_id` UUID FK→
scoring_rule_versions NULL. (Partitioned table — additive column is safe.)

### 10.4 Source domains + Domain Authority (migration 0010)

**`source_domains`** (our aggregate)
- `id`, `workspace_id`, `project_id` UUID NULL (NULL = workspace‑wide rollup) —
  🟦 recommend **per‑(workspace, domain_key)** primary aggregate + a per‑project
  view via query, to avoid row explosion; confirm grain `❓`
- `domain_key` String(255), `grouping` enum(`registrable|platform_host`),
  `backlink_count` int, `indexed_count` int, `not_indexed_count` int,
  `dofollow_count` int, `duplicate_count` int, `avg_score` numeric,
  `link_type_distribution` JSONB, `last_recomputed_at`,
  `domain_authority_id` UUID FK→domain_authority_results NULL
- *Constraints:* unique(`workspace_id`,`domain_key`); index(`workspace_id`,
  `domain_key`)

**`backlink_records`** (extend): add `source_domain_id` UUID FK→source_domains
NULL, indexed. (Backfill from existing `source_domain` string.)

**`domain_authority_results`** (current DA per domain — merged source_domain_metrics)
- `id`, `workspace_id` NULL (DA is domain‑intrinsic; 🟦 could be global cache),
  `domain_key` String(255), `provider` String, `da` int NULL, `pa` int NULL,
  `spam_score` int NULL, `global_rank` bigint NULL, `monthly_visits` bigint NULL,
  `raw` JSONB, `fetched_at`, `expires_at`
- *Constraints:* unique(`domain_key`,`provider`); index(`expires_at`)
- > 🟦 Make DA a **workspace‑agnostic global cache** keyed by `(domain_key,
  provider)` — DA for `forbes.com` is the same for every workspace, so don't refetch
  per tenant. Confirm `❓`.

**`domain_authority_history`** (append‑only)
- `id`, `domain_key`, `provider`, `da`,`pa`,`spam_score`,`global_rank`,
  `monthly_visits`, `captured_at`
- *Index:* (`domain_key`,`captured_at`)

### 10.5 Competitor / Market (migration 0011)

**`competitor_sheets`**
- `id`, `workspace_id`, `project_id` FK→projects, `name`, `source_kind`
  enum(`file|google_sheet`), `spreadsheet_id`/`upload_key` String NULL,
  `column_mapping` JSONB, `status`, `created_by`, `deleted_at`,`deleted_by`
- *Index:* (`workspace_id`,`project_id`)

**`competitor_sheet_imports`** (run log — or reuse `imports` with a kind flag)
- `id`, `competitor_sheet_id` FK, `status`, `total_rows`, `valid_rows`,
  `invalid_rows`, `new_domains`, `existing_domains`, `error`, timestamps

**`competitor_backlinks`** (separate from our links)
- `id`, `workspace_id`, `project_id`, `competitor_sheet_id` FK,
  `source_page_url`, `source_url_normalized`, `source_domain_key`,
  `competitor_source_domain_id` FK, `target_url` NULL, `anchor_text` NULL,
  `rel` NULL, `link_type_id` FK→link_types NULL, `link_type_confidence`
  enum(`high|low|none|confirmed`), `categorization_source`
  enum(`inherited_single|inherited_majority|manual|none`),
  `index_status` NULL, `qa_category` enum (see F17), timestamps
- *Index:* (`competitor_sheet_id`), (`workspace_id`,`source_domain_key`)

**`competitor_source_domains`**
- `id`, `workspace_id`, `project_id`, `competitor_sheet_id` FK NULL,
  `domain_key`, `grouping`, `url_count` int, `indexed_count` int,
  `link_type_id` NULL, `link_type_confidence`, `domain_authority_id` FK NULL,
  timestamps
- *Constraints:* unique(`workspace_id`,`project_id`,`domain_key`)

**`competitor_domain_comparisons`** (the insight bridge)
- `id`, `workspace_id`, `project_id`, `competitor_source_domain_id` FK,
  `our_source_domain_id` FK NULL, `category`
  enum(`existing|new_opportunity|already_used_exact|needs_review`),
  `our_link_count` int, `competitor_link_count` int, `our_indexed_pct` numeric,
  `da` int NULL, `opportunity_score` numeric, `recommended_action` String,
  `status` enum(`open|accepted|rejected|in_progress|done`),
  `assigned_user_id` FK NULL, timestamps
- *Index:* (`workspace_id`,`project_id`,`category`), (`opportunity_score`)

### 10.6 Reports freeze (migration 0012)

**`report_snapshots`** (true row‑level freeze)
- `id`, `report_id` FK→reports, `row_index` int, `data` JSONB (the frozen row),
  `created_at` — OR a single `snapshot_blob_key` pointing at object storage for
  large reports. 🟦 For 1–2M scale, store the frozen file in object storage and
  keep only metadata here (mirrors how `reports.file_key` already works), rather
  than millions of JSONB rows. Confirm grain `❓`.

### 10.7 Indexing & constraints summary

- Every new table: index on `workspace_id`; tenant filter on every query.
- Soft‑delete tables: composite index `(workspace_id, deleted_at)` or partial index
  `WHERE deleted_at IS NULL` for hot paths.
- Uniqueness: `project_domains(project_id,domain)`; `link_types(workspace_id,slug)`;
  `employee_codes(workspace_id,code)`; `source_domains(workspace_id,domain_key)`;
  `domain_authority_results(domain_key,provider)`;
  `google_sheet_project_tabs(sheet_source_id,gid)`.
- Partitioning: no new partitioned tables required; `domain_authority_history` and
  `competitor_backlinks` grow but slowly/boundedly — revisit partitioning only if
  competitor data approaches the millions (§13).

---

## 11. Feature‑by‑Feature Implementation Plan

> Each block uses your required format. "FILES TO CHANGE" lists the real paths in
> this repo. Tasks are ordered. Confirmations gating a feature are tagged.

---

### FEATURE 1 — Project Settings with Main Domain

**FEATURE GOAL:** Give each project a settings surface whose **main domain(s)**
become the canonical target for that project's backlink QA, and which carry
per‑project policy (scoring profile, status thresholds, schedule).

**CURRENT PROJECT AREA AFFECTED:** `projects` model, link‑matching in
`crawler/engine.py` + `qa/checks/links.py`, dedup key on `backlink_records`,
reports & analytics that show "target."

**USER ROLES AFFECTED:** Admin, Manager (edit); QA, Viewer (read).

**BUSINESS LOGIC:**
- `✅` A project has one primary main domain and optionally secondary domains
  (`project_domains`). `❓A` confirm one‑vs‑many and matching semantics.
- `🟦` Matching rule (recommended): a source page "has the backlink" if it links to
  any URL whose registrable/platform domain ∈ project domains; the specific matched
  URL is still recorded. Per‑row `target_url` becomes optional/secondary.
- `✅` Changing the main domain is audited; old QA history stays linked to the crawl
  that produced it (history immutable). A main‑domain change **does not** rewrite
  past verdicts unless an explicit re‑match/re‑score is run.

**USER FLOW:** Project → Settings tab → edit Main Domain(s) (add/remove/set
primary) + policy → validate → save → optional "re‑match & re‑score now" prompt.
(See flowchart §8.1.)

**DATABASE CHANGES:** new `project_settings` (1:1), new `project_domains` (1:N),
migrate `Project.treat_sponsored_as_follow`/policy into settings (keep column for
back‑compat, read from settings). Soft‑delete cols on `projects`.

**BACKEND CHANGES:** `project_settings_service.py`; extend `project_service`;
new `api/v1/project_settings.py`; change link‑matching to consult project domains
(behind a feature flag + `❓A`); `tasks.scoring.rescore_project` (shared with F8).

**FRONTEND AND UX CHANGES:** new Settings desk with a Main Domains editor
(chips + primary toggle), validation, and the re‑score confirmation modal.

**FILES TO CHANGE:** `backend/app/models/project.py`, new
`backend/app/models/project_settings.py`, new `backend/app/models/project_domain.py`,
`backend/app/services/project_service.py`, new
`backend/app/services/project_settings_service.py`,
`backend/app/api/v1/project_settings.py`, `backend/app/main.py` (router mount),
`backend/app/crawler/engine.py` (+`qa/checks/links.py`) for match authority,
`backend/alembic/versions/0007_*.py`, `frontend/components/workspace-app.tsx`
(+ new `components/desks/SettingsDesk.tsx`), `frontend/lib/api.ts`.

**DEVELOPMENT TASKS:** 1) migration + models; 2) settings service + API (CRUD,
validation, audit); 3) domains editor UI; 4) `❓A` decide matching semantics →
implement behind flag; 5) re‑score job (after F8) ; 6) tests.

**TESTING CHECKLIST:** create/update settings; add/remove domains; exactly‑one
primary enforced; invalid domain rejected; duplicate domain rejected; warn on
cross‑project domain reuse; audit row written on change; permission denied for
Viewer/QA; matching uses new domains (when enabled); history preserved on change.

---

### FEATURE 2 — User and Employee Code Management

**FEATURE GOAL:** Manage app users + employee codes, and reconcile Google‑Sheet
user labels/codes to internal users so reports work by real identity.

**CURRENT PROJECT AREA AFFECTED:** `users`/`workspace_members`, free‑text
`assigned_user_label`/`employee_code` on backlinks, `assignment_history`,
team management (`team_service`, `api/v1/team.py`).

**USER ROLES AFFECTED:** Admin (full), Manager (assign within scope), others read.

**BUSINESS LOGIC:**
- `✅` Manual add/edit user, assign/update employee code, active/inactive.
- `❓F` code uniqueness scope + multi‑code/reassignment rules.
- `🟦` Reconciliation: build distinct (label, code) set from backlinks; suggest
  mappings (exact > code‑match > unmapped); admin confirms; optional backfill of
  `backlink_records.assigned_user_id`.

**USER FLOW:** Settings → Users & Codes → add/edit users, manage codes, review
"unmapped sheet users," confirm mappings. (Flowchart §8.3.)

**DATABASE CHANGES:** new `employee_codes`, `user_employee_mappings`; reuse
`assignment_history`; optional `backlink_records.employee_code_id` FK (keep string
too for sheet fidelity). Soft delete on codes.

**BACKEND CHANGES:** `employee_service.py`; extend `team_service`; new/extended
`api/v1/users.py` (or `team.py`); reconciliation query + suggest endpoint.

**FRONTEND AND UX CHANGES:** Users table (add/edit/active), Codes table, an
"Unmapped sheet users" review queue with one‑click mapping.

**FILES TO CHANGE:** new `backend/app/models/employee.py`,
`backend/app/services/employee_service.py`, `backend/app/services/team_service.py`,
`backend/app/api/v1/team.py` (or new `users.py`), `0007_*.py`,
`frontend/components/workspace-app.tsx` (+ `TeamDesk`/new `UsersDesk`),
`frontend/lib/api.ts`.

**DEVELOPMENT TASKS:** 1) models+migration; 2) code CRUD + uniqueness (`❓F`);
3) mapping CRUD + reconciliation suggest; 4) UI tables + review queue; 5) optional
backfill job; 6) tests.

**TESTING CHECKLIST:** add/edit user; assign/update code; duplicate code rejected
per rule; deactivate user; map sheet label→user; reassign code (history kept);
reports group correctly by mapped user vs raw label; permissions enforced.

---

### FEATURE 3 — Project‑Level Scoring Settings

**FEATURE GOAL:** Let a project override scoring per link type (e.g. Project A
scores Web 2.0 differently), falling back to link‑type/global defaults.

**CURRENT PROJECT AREA AFFECTED:** `qa/scoring.py` (severity model today),
`qa/engine.py`, `crawl_results` (stores breakdown), reports/analytics.

**USER ROLES AFFECTED:** Admin, Manager (edit project rules); others read.

**BUSINESS LOGIC:** `❓B` model shape. `🟦` Resolution order: project+link_type →
project+ANY → link_type(global) → global default; chosen version recorded on the
crawl result (Flowchart §8.4). Project overrides are versioned snapshots.

**DATABASE CHANGES:** `scoring_rule_versions` rows with `scope=project` (+ optional
`link_type_id`); `crawl_results.scoring_rule_version_id`.

**BACKEND CHANGES:** `scoring_rules_service.py` (resolver + CRUD + versioning);
rewire `qa/engine.py` to use the resolver (after F8 lands the parameter model).

**FRONTEND AND UX CHANGES:** Settings → Scoring → per‑link‑type override editor
with "inherits global" indicators and a live preview ("a dofollow indexed Web 2.0
link would score N").

**FILES TO CHANGE:** new `backend/app/models/scoring.py`, new
`backend/app/services/scoring_rules_service.py`, `backend/app/qa/engine.py`,
`backend/app/qa/scoring.py`, `backend/app/api/v1/scoring.py`, `0009_*.py`,
`frontend/components/workspace-app.tsx` (+ `ScoringDesk`), `frontend/lib/api.ts`.

**DEVELOPMENT TASKS:** depends on F8; 1) project‑scope rule CRUD + versioning;
2) resolver integration; 3) override UI + preview; 4) tests for fallback order.

**TESTING CHECKLIST:** project rule overrides global; fallback chain correct;
version pinned on crawl result; preview matches actual score; changing a rule
creates a new version and does not alter past results; permissions.

---

### FEATURE 4 — Global Backlink Type Scoring Settings

**FEATURE GOAL:** Workspace‑wide default scoring per link type (Web 2.0, Profile,
Guest Post, Blog Comment…), overridable per project (F3).

**CURRENT PROJECT AREA AFFECTED:** same scoring stack as F3; `link_types` catalog.

**USER ROLES AFFECTED:** Admin only (edit global) `❓J`; Manager read.

**BUSINESS LOGIC:** `✅` global defaults per link type + a baseline default for
unknown types; `🟦` versioned; new permission `MANAGE_SCORING` (Admin) and
`EDIT_PROJECT_SCORING` (Manager+).

**DATABASE CHANGES:** `scoring_rule_versions` rows with `scope=global` and
`scope=link_type`; seed a sane baseline.

**BACKEND CHANGES:** scoring service (shared with F3); new permissions in
`core/rbac.py`; seed defaults in `db/seed.py`.

**FRONTEND AND UX CHANGES:** Settings → Global Scoring (Admin), grid of
link‑type × parameter weights with reset‑to‑default.

**FILES TO CHANGE:** `backend/app/core/rbac.py`, `backend/app/db/seed.py`,
`backend/app/services/scoring_rules_service.py`, `backend/app/api/v1/scoring.py`,
`0009_*.py`, `frontend/components/workspace-app.tsx`.

**DEVELOPMENT TASKS:** 1) permissions; 2) global/link‑type rule CRUD+versioning;
3) seed defaults; 4) Admin UI; 5) tests.

**TESTING CHECKLIST:** only Admin edits global; link‑type default applies when no
project override; baseline default for unknown type; versioning; seed present on
fresh DB.

---

### FEATURE 5 — Link Type Detection from Google Sheet Sub‑Sheets

**FEATURE GOAL:** Detect all tabs in a project spreadsheet and treat tab names as
link types.

**CURRENT PROJECT AREA AFFECTED:** `integrations/google_sheets.py` (single‑tab
today), `sheet_sync_service.py`, `sheet_sources` model.

**USER ROLES AFFECTED:** Admin, Manager.

**BUSINESS LOGIC:** `❓D` confirm tabs = link types. `✅` Enumerate worksheets;
upsert `google_sheet_project_tabs` keyed by **gid** (stable across renames); new
tab → `needs_mapping`; deleted tab → `missing` (don't delete imported links).

**USER FLOW / FLOWCHART:** §8.2 (detection half).

**DATABASE CHANGES:** new `google_sheet_project_tabs`; relax `sheet_sources` tab
uniqueness (§10.2).

**BACKEND CHANGES:** add `google_sheets.list_worksheets()` (returns name+gid);
`sheet_tab_service.detect_tabs()`; call during sync.

**FRONTEND AND UX CHANGES:** Sheets desk shows detected tabs + status badges.

**FILES TO CHANGE:** `backend/app/integrations/google_sheets.py`, new
`backend/app/services/sheet_tab_service.py`, `backend/app/services/sheet_sync_service.py`,
new `backend/app/models/sheet_tab.py`, `backend/app/api/v1/sheets.py`, `0008_*.py`,
`frontend/components/workspace-app.tsx` (SheetsDesk).

**DEVELOPMENT TASKS:** 1) list_worksheets; 2) tabs model+migration; 3) detect on
sync; 4) UI listing; 5) drift handling tests.

**TESTING CHECKLIST:** detect N tabs; gid stable on rename; new tab flagged;
deleted tab flagged missing without data loss; first‑worksheet default still works
for legacy single‑tab sheets.

---

### FEATURE 6 — Sub‑Sheet Selection with Checkboxes

**FEATURE GOAL:** Choose which tabs import / are QA‑checked / are active, and map
each tab → link type.

**CURRENT PROJECT AREA AFFECTED:** sheet sync/import pipeline; backlink `link_type`.

**USER ROLES AFFECTED:** Admin, Manager.

**BUSINESS LOGIC:** `✅` only `import_enabled & is_active` tabs are synced;
`qa_enabled` controls whether crawls run for that tab's links; tab→link_type
mapping sets `backlink_records.link_type`(_id). Ignored/unmapped tabs skipped.

**USER FLOW / FLOWCHART:** §8.2 (selection half).

**DATABASE CHANGES:** new `google_sheet_subsheet_mappings`.

**BACKEND CHANGES:** `sheet_tab_service.set_mappings()`; sync respects flags; set
link type from mapping during import.

**FRONTEND AND UX CHANGES:** per‑tab row with checkboxes (import/QA/active) +
link‑type dropdown (with "create new type"); bulk select.

**FILES TO CHANGE:** `backend/app/services/sheet_tab_service.py`,
`backend/app/services/sheet_sync_service.py`,
`backend/app/services/import_service.py` (apply tab link type),
`backend/app/api/v1/sheets.py`, `0008_*.py`, `frontend/components/workspace-app.tsx`.

**DEVELOPMENT TASKS:** 1) mappings model; 2) selection API; 3) sync honoring flags;
4) link‑type assignment on import; 5) UI; 6) tests.

**TESTING CHECKLIST:** unchecked tab not imported; QA‑disabled tab not crawled;
link type applied correctly; create‑new‑type from dropdown; toggling re‑sync picks
up changes; ignored tab stays ignored.

---

### FEATURE 7 — Dynamic Delete and Confirmation System

**FEATURE GOAL:** Safe, audited, dependency‑aware deletes (soft delete + restore)
across projects, sheets, tab mappings, users, codes, scoring rules, imported
links, competitor sheets, market data.

**CURRENT PROJECT AREA AFFECTED:** all delete paths (currently hard delete);
`audit_logs`.

**USER ROLES AFFECTED:** Admin, Manager (scoped) per entity permission.

**BUSINESS LOGIC:** `❓I` scope/window. `🟦` soft delete + dependency preflight +
typed confirmation for high‑impact + audit; restore window then audited purge.
Project delete asks: archive (keep history) vs delete links+history.

**USER FLOW / FLOWCHART:** §8.11.

**DATABASE CHANGES:** `deleted_at`/`deleted_by` on soft‑deletable tables; reuse
`audit_logs` (action=DELETE with dependent counts in `before`/`after`).

**BACKEND CHANGES:** `delete_service.py` (preflight counts + soft delete + restore
+ purge); add `?soft` semantics to existing delete endpoints; global query filter
helper `deleted_at IS NULL`.

**FRONTEND AND UX CHANGES:** shared `ConfirmDelete` modal (dependency preview,
type‑to‑confirm), a "Recently deleted / Restore" view.

**FILES TO CHANGE:** new `backend/app/services/delete_service.py`,
`backend/app/services/project_service.py` + other services, all relevant
`api/v1/*.py` delete endpoints, `0007_*.py` (soft‑delete cols),
`frontend/components/workspace-app.tsx` (+ shared modal), `frontend/lib/api.ts`.

**DEVELOPMENT TASKS:** 1) soft‑delete columns + query filters; 2) preflight counts;
3) soft delete + audit; 4) restore + purge job; 5) confirm modal; 6) tests.

**TESTING CHECKLIST:** preflight returns correct dependent counts; soft delete
hides but preserves; restore works in window; purge after window; project archive
keeps history; audit row complete; permission gating; no accidental cascade of
unrelated data.

---

### FEATURE 8 — Dynamic Parameter Scoring

**FEATURE GOAL:** Configurable per‑parameter weights/outcomes driving the score,
the engine that F3/F4 configure.

**CURRENT PROJECT AREA AFFECTED:** `qa/scoring.py`, `qa/engine.py`, `qa/types.py`,
`crawl_results.score_breakdown`, reports/analytics.

**USER ROLES AFFECTED:** Admin/Manager configure; system applies.

**BUSINESS LOGIC:** `❓B/C`. `🟦` Option B1: a fixed `scoring_parameters` registry;
each rule version maps parameter → weight + outcome→points; score = normalised
weighted sum; hard safety rules stay fixed; status bands configurable. The 32 QA
checks still run and produce issues/evidence (they feed parameter outcomes).
Re‑score job writes **new** crawl results, never mutates old ones.

**USER FLOW / FLOWCHART:** §8.4.

**DATABASE CHANGES:** `scoring_parameters` (seed); `scoring_rule_versions.rules`
JSONB schema; `crawl_results.scoring_rule_version_id`.

**BACKEND CHANGES:** new `qa/scoring_params.py` (registry + extractor:
artifact+issues → outcomes); rewrite `score_issues` → `score_parameters` behind the
resolver; `tasks/scoring.py` re‑score job on the (revived) `qa` queue.

**FRONTEND AND UX CHANGES:** parameter‑weight editor (shared by F3/F4) with live
preview + "re‑score project" action (audited, async, progress).

**FILES TO CHANGE:** `backend/app/qa/engine.py`, `backend/app/qa/scoring.py`,
new `backend/app/qa/scoring_params.py`, new `backend/app/workers/tasks/scoring.py`,
`backend/app/workers/celery_app.py` (route to `qa`),
`backend/app/services/scoring_rules_service.py`, `0009_*.py`,
`frontend/components/workspace-app.tsx`.

**DEVELOPMENT TASKS:** 1) `❓B` decide model; 2) parameter registry + extractor;
3) resolver + scoring function; 4) pin version on results; 5) re‑score job; 6) UI
preview; 7) extensive tests (golden cases).

**TESTING CHECKLIST:** parameter weight changes alter score deterministically;
normalisation to 0–100; hard‑fail rules still fire; band thresholds; rule‑version
pinned; re‑score creates new results; old reports unchanged; preview == actual;
performance on a large project.

---

### FEATURE 9 — Source Main‑Domain Extraction (+ aggregate)

**FEATURE GOAL:** Group every source URL under its source main domain and maintain
an aggregate per domain.

**CURRENT PROJECT AREA AFFECTED:** `normalize.py` (already extracts registrable
domain), `backlink_records.source_domain` (already populated), import/crawl upsert.

**USER ROLES AFFECTED:** all (read analytics).

**BUSINESS LOGIC:** `❓E` registrable vs platform‑host grouping. `🟦` reuse
`registrable_domain()`; add a `PLATFORM_HOST_LIST` for Web‑2.0 hosts grouped by
full host; aggregate counts via scheduled recompute (avoid the LinkIdentity
freshness trap, §2.3#4).

**USER FLOW / FLOWCHART:** §8.5.

**DATABASE CHANGES:** new `source_domains` aggregate; `backlink_records.
source_domain_id` FK (backfill from existing string).

**BACKEND CHANGES:** `source_domain_service.py` (extract grouping + recompute);
hook into import/crawl upsert to set `source_domain_id`; beat job
`recompute-source-domain-rollups`.

**FRONTEND AND UX CHANGES:** none yet (F10 consumes it).

**FILES TO CHANGE:** `backend/app/crawler/normalize.py` (platform‑host helper),
new `backend/app/services/source_domain_service.py`,
`backend/app/services/import_service.py` (+ result/crawl upsert),
new `backend/app/models/source_domain.py`,
new `backend/app/workers/tasks/source_domains.py`,
`backend/app/workers/celery_app.py` (beat), `0010_*.py`.

**DEVELOPMENT TASKS:** 1) grouping helper (`❓E`); 2) aggregate model+migration+
backfill; 3) FK + upsert hook; 4) recompute job; 5) tests.

**TESTING CHECKLIST:** `www.x.com` & `x.com` group together; Web‑2.0 hosts grouped
per chosen rule; invalid URL excluded; counts correct after recompute; backfill
populates FK for existing rows; rollup stays fresh after new imports.

---

### FEATURE 10 — Source Main‑Domain Analytics Dashboard

**FEATURE GOAL:** A dashboard listing source main domains with their analytics
(totals, indexed %, link‑type mix, users, projects, QA/HTTP/rel summaries,
duplicates, avg score, DA, crawl‑failure rate, trend).

**CURRENT PROJECT AREA AFFECTED:** `analytics_service.py` (whitelist),
`api/v1/analytics.py`, UI.

**USER ROLES AFFECTED:** all (scoped).

**BUSINESS LOGIC:** `✅` read `source_domains` + DA + (optional) history trend;
add `source_domain` as an analytics **dimension** (whitelist) and a dedicated
endpoint for the per‑domain drill‑down.

**USER FLOW:** Source Domains desk → sortable/filterable table → click a domain →
drill‑down with all metrics + its backlinks.

**DATABASE CHANGES:** none beyond F9/F16 (reads aggregates).

**BACKEND CHANGES:** extend `analytics_service.py` dimension map; new
`api/v1/source_domains.py` (list + detail); reuse keyset pagination.

**FRONTEND AND UX CHANGES:** new Source Domains desk (table + drill‑down),
reusing existing helper components (`Metric`, `Status`, `IndexBadge`, `Th/Td`).

**FILES TO CHANGE:** `backend/app/services/analytics_service.py`,
`backend/app/services/source_domain_service.py`,
new `backend/app/api/v1/source_domains.py`, `backend/app/main.py`,
`frontend/components/workspace-app.tsx` (+ `SourceDomainsDesk`), `frontend/lib/api.ts`.

**DEVELOPMENT TASKS:** 1) dimension + queries; 2) list/detail endpoints; 3) desk
UI + drill‑down; 4) trend (if history available); 5) tests.

**TESTING CHECKLIST:** percentages sum correctly; scope switch (company/project)
works; sort/filter/pagination; drill‑down lists correct backlinks; DA shown when
present, graceful "—" when absent; large‑volume performance.

---

### FEATURE 11 — Market / Competitor Sheet Upload

**FEATURE GOAL:** Upload competitor backlink sheets into a project (multiple per
project), stored separately from our verified backlinks.

**CURRENT PROJECT AREA AFFECTED:** import pipeline (reuse), storage, new
competitor tables.

**USER ROLES AFFECTED:** Admin, Manager, QA (import permission).

**BUSINESS LOGIC:** `❓H` format/source. `🟦` support file + Google‑Sheet URL;
reuse `import_parse`/`import_service` patterns; competitor data never mixes with
`backlink_records`.

**USER FLOW / FLOWCHART:** §8.6.

**DATABASE CHANGES:** new `competitor_sheets`, `competitor_sheet_imports`,
`competitor_backlinks`, `competitor_source_domains` (migration 0011).

**BACKEND CHANGES:** `competitor_service.py` (upload+stage+normalize+persist);
`tasks/competitors.py` (async import); reuse storage + normalize.

**FRONTEND AND UX CHANGES:** Competitors desk → Upload (file/URL) + column map +
progress.

**FILES TO CHANGE:** new `backend/app/models/competitor.py`,
new `backend/app/services/competitor_service.py`,
new `backend/app/workers/tasks/competitors.py`,
new `backend/app/api/v1/competitors.py`, `backend/app/main.py`, `0011_*.py`,
`frontend/components/workspace-app.tsx` (+ `CompetitorsDesk`), `frontend/lib/api.ts`.

**DEVELOPMENT TASKS:** 1) models+migration; 2) upload+parse+normalize; 3) async
import job; 4) UI upload+mapping; 5) tests.

**TESTING CHECKLIST:** CSV+XLSX+Sheet URL ingest; invalid rows counted not fatal;
multiple sheets per project; competitor rows isolated from project backlinks;
large sheet performance; permission gating.

---

### FEATURE 12 — Competitor Sheet Mapping and Validation

**FEATURE GOAL:** Map competitor columns to canonical fields and validate before
analysis.

**CURRENT PROJECT AREA AFFECTED:** competitor import; `import_parse.auto_map`.

**USER ROLES AFFECTED:** Admin, Manager, QA.

**BUSINESS LOGIC:** `✅` require a source URL column; auto‑map known headers; lenient
on unknown columns (store raw); validation report (valid/invalid/new/existing
domain counts).

**USER FLOW:** after upload → mapping preview → validate → confirm → analyze.

**DATABASE CHANGES:** `competitor_sheets.column_mapping` JSONB;
`competitor_sheet_imports` counts.

**BACKEND CHANGES:** reuse `import_parse`; competitor‑specific validators in
`competitor_service`.

**FRONTEND AND UX CHANGES:** mapping UI (reuse import preview pattern) + validation
summary.

**FILES TO CHANGE:** `backend/app/services/import_parse.py` (if extended),
`backend/app/services/competitor_service.py`, `backend/app/api/v1/competitors.py`,
`frontend/components/workspace-app.tsx`.

**DEVELOPMENT TASKS:** 1) auto‑map + validators; 2) preview endpoint; 3) UI;
4) tests.

**TESTING CHECKLIST:** missing source‑URL column rejected; auto‑map common headers;
unknown columns preserved; validation counts correct; re‑map and re‑validate.

---

### FEATURE 13 — Existing vs New Source‑Domain Comparison

**FEATURE GOAL:** Compare competitor source domains to our project's existing
source domains; categorise EXISTING vs NEW_OPPORTUNITY with metrics + recommended
action.

**CURRENT PROJECT AREA AFFECTED:** `source_domains` (F9), competitor tables, DA.

**USER ROLES AFFECTED:** Admin, Manager, QA (off‑page).

**BUSINESS LOGIC / FLOWCHART:** §8.7. `✅` join on `domain_key`; EXISTING attaches
our counts/indexed%/link‑types/score/DA/users; NEW attaches competitor URLs +
estimated link type (F14) + DA + indexed%.

**DATABASE CHANGES:** new `competitor_domain_comparisons`.

**BACKEND CHANGES:** `competitor_service.compare()`; `tasks/competitors.compare`.

**FRONTEND AND UX CHANGES:** Competitors desk → comparison view grouped by
category with filters.

**FILES TO CHANGE:** `backend/app/services/competitor_service.py`,
`backend/app/workers/tasks/competitors.py`, `backend/app/api/v1/competitors.py`,
new `backend/app/models/competitor.py` (comparison table), `0011_*.py`,
`frontend/components/workspace-app.tsx`.

**DEVELOPMENT TASKS:** 1) comparison model; 2) compare logic + job; 3) endpoints;
4) UI grouping; 5) tests (edge: same domain different grouping rule).

**TESTING CHECKLIST:** existing detected; new detected; counts/percent correct;
recommended action set; re‑run idempotent; respects platform‑host grouping.

---

### FEATURE 14 — Auto Link‑Type Categorisation

**FEATURE GOAL:** Auto‑assign link type to competitor links by inheriting from our
domain patterns; flag ambiguous/unknown; allow manual override.

**CURRENT PROJECT AREA AFFECTED:** competitor links, `link_types`, our backlink
link‑type distribution.

**USER ROLES AFFECTED:** Admin, Manager, QA.

**BUSINESS LOGIC / FLOWCHART:** §8.8. `✅` single known type → HIGH confidence;
multiple → AMBIGUOUS (store candidates); unseen → UNKNOWN; manual override =
confirmed; persist confidence + source.

**DATABASE CHANGES:** `competitor_backlinks.link_type_id` + `link_type_confidence`
+ `categorization_source`.

**BACKEND CHANGES:** `competitor_service.categorize()` using our source‑domain →
link‑type distribution.

**FRONTEND AND UX CHANGES:** review queue for ambiguous/unknown with quick assign;
confidence badges.

**FILES TO CHANGE:** `backend/app/services/competitor_service.py`,
`backend/app/api/v1/competitors.py`, `frontend/components/workspace-app.tsx`.

**DEVELOPMENT TASKS:** 1) distribution lookup; 2) categorise + persist; 3) override
endpoint; 4) review UI; 5) tests.

**TESTING CHECKLIST:** single‑type inherit; ambiguous flagged with candidates;
unknown flagged; override persists + audited; confidence/source stored.

---

### FEATURE 15 — Competitor Opportunity Reports

**FEATURE GOAL:** Generate ranked opportunity reports (new vs existing domains)
with DA, index, gap, and recommended action — as frozen snapshots, exportable.

**CURRENT PROJECT AREA AFFECTED:** report worker (`tasks/reports.py`), reports
model, competitor comparisons.

**USER ROLES AFFECTED:** Admin, Manager, QA (export permission).

**BUSINESS LOGIC / FLOWCHART:** §8.10. `✅` opportunity score = f(DA band, indexed%,
our gap, link‑type value weight, competitor frequency); freeze rows at generation.

**DATABASE CHANGES:** reuse `reports` (new `report_type` enum values:
`COMPETITOR_OPPORTUNITY`); new `report_snapshots` for true freeze (§10.6).

**BACKEND CHANGES:** extend report worker with competitor report types + snapshot
writing; opportunity scoring in `competitor_service`.

**FRONTEND AND UX CHANGES:** Competitors → Reports (build + download + versions),
reusing ReportsDesk patterns.

**FILES TO CHANGE:** `backend/app/models/enums.py` (ReportType),
`backend/app/workers/tasks/reports.py`, `backend/app/services/report_service.py`,
`backend/app/services/competitor_service.py`, `0012_*.py`,
`frontend/components/workspace-app.tsx`.

**DEVELOPMENT TASKS:** 1) report type + scoring; 2) snapshot freeze; 3) worker
rows; 4) UI; 5) tests.

**TESTING CHECKLIST:** ranking correct; new/existing grouping; snapshot frozen
(unchanged after later data changes); formats CSV/XLSX/PDF; versioning.

---

### FEATURE 16 — Domain Authority Checking Using RapidAPI Moz

**FEATURE GOAL:** Fetch + cache DA per source/competitor main domain, with history,
feeding scoring/analytics/opportunities.

**CURRENT PROJECT AREA AFFECTED:** `integrations/site_metrics.py` (already supports
Moz RapidAPI/official + Similarweb, Redis‑cached, disabled by default).

**USER ROLES AFFECTED:** system (background); Admin configures provider.

**BUSINESS LOGIC / FLOWCHART:** §8.9. `❓G` provider + budget. `🟦` reuse
`site_metrics` provider abstraction; move storage to a DB table keyed by
`(domain_key,provider)` + append history; refresh on TTL; degrade gracefully.

**DATABASE CHANGES:** new `domain_authority_results` (current) +
`domain_authority_history` (append‑only). `source_domains.domain_authority_id` FK.

**BACKEND CHANGES:** `domain_authority_service.py` wrapping `site_metrics`;
`tasks/domain_authority.py` (batched/staggered fetch, like `index.check`); beat
`refresh-domain-authority-due`.

**FRONTEND AND UX CHANGES:** DA shown in source‑domain + competitor views; provider
config in Settings (key handling via env/`settings` table, never hardcoded — §
golden rules).

**FILES TO CHANGE:** `backend/app/integrations/site_metrics.py` (minor),
new `backend/app/services/domain_authority_service.py`,
new `backend/app/workers/tasks/domain_authority.py`,
`backend/app/workers/celery_app.py`, new `backend/app/models/domain_authority.py`,
`backend/app/core/config.py` (already has the knobs), `0010_*.py`,
`frontend/components/workspace-app.tsx`.

**DEVELOPMENT TASKS:** 1) DA tables+migration; 2) service over site_metrics;
3) batched fetch job + cache TTL; 4) wire into source_domains; 5) tests (mock API).

**TESTING CHECKLIST:** fetch + cache hit; TTL refresh; history appended; API
failure non‑blocking; quota/backoff respected; global cache reused across
workspaces (`❓G`); no key leakage.

---

### FEATURE 17 — Competitor Link QA Categorisation

**FEATURE GOAL:** Categorise competitor links for opportunity planning (existing
domain / new domain / existing exact URL / new URL / type match / new opportunity /
unknown / ambiguous / high‑value / low‑value / already used / needs review).

**CURRENT PROJECT AREA AFFECTED:** competitor links, comparisons, DA.

**USER ROLES AFFECTED:** Admin, Manager, QA (off‑page).

**BUSINESS LOGIC:** `✅` derive category from comparison (F13) + auto‑type (F14) +
DA + index + exact‑URL membership in our data; high/low value from DA band + link
type value weight. `❓` confirm exact value thresholds.

**DATABASE CHANGES:** `competitor_backlinks.qa_category` enum; reuse comparison
table.

**BACKEND CHANGES:** `competitor_service.categorize_qa()`.

**FRONTEND AND UX CHANGES:** filters + grouping by category; review actions.

**FILES TO CHANGE:** `backend/app/models/competitor.py` (enum),
`backend/app/services/competitor_service.py`, `backend/app/api/v1/competitors.py`,
`frontend/components/workspace-app.tsx`.

**DEVELOPMENT TASKS:** 1) category enum + rules; 2) compute on import/compare;
3) filters; 4) tests.

**TESTING CHECKLIST:** each category assigned on representative inputs; exact‑URL
already‑used detection; high/low value thresholds; needs‑review fallback.

---

### FEATURE 18 — Off‑Page Team Workflow Dashboard

**FEATURE GOAL:** A workflow board for the off‑page team to act on opportunities
(open → accepted → in‑progress → done), with assignment and filters.

**CURRENT PROJECT AREA AFFECTED:** comparisons, users, assignments.

**USER ROLES AFFECTED:** Manager, QA (off‑page); Admin oversight.

**BUSINESS LOGIC:** `✅` opportunities (from `competitor_domain_comparisons`) get a
`status` + `assigned_user_id`; transitions audited; filter by status/DA/type/user.

**USER FLOW:** Competitors → Off‑Page board → assign + move status → export.

**DATABASE CHANGES:** `competitor_domain_comparisons.status` + `assigned_user_id`
(already in §10.5).

**BACKEND CHANGES:** `competitor_service` status transitions + assignment;
endpoints.

**FRONTEND AND UX CHANGES:** board/list with status columns, assignment, filters
(reuse helper components; keep it list‑based for 1–2M scale, not drag‑heavy).

**FILES TO CHANGE:** `backend/app/services/competitor_service.py`,
`backend/app/api/v1/competitors.py`, `frontend/components/workspace-app.tsx`.

**DEVELOPMENT TASKS:** 1) status/assignment API; 2) board UI; 3) audit; 4) tests.

**TESTING CHECKLIST:** assign opportunity; transition status; audit recorded;
filter by user/status; permission gating; performance with many opportunities.

---

### FEATURE 19 — Report Export to Google Sheets

**FEATURE GOAL:** Export reports (incl. competitor opportunities) to a Google Sheet
tab, reusing the existing write‑back mechanism.

**CURRENT PROJECT AREA AFFECTED:** `google_sheets.write_back`, report worker,
`reports.output_target` (already exists: `download|google_sheet`).

**USER ROLES AFFECTED:** Admin, Manager (export permission); SA needs Editor.

**BUSINESS LOGIC:** `❓H` target sheet/tab choice. `🟦` write to a dedicated results
tab (new tab per export or fixed tab), never overwriting input columns (existing
`write_back` already guarantees this for the gap‑column approach; for a *new tab*
add `create_tab` support).

**USER FLOW:** Report builder → output target = Google Sheet → choose spreadsheet/
tab → generate → confirm (outward‑facing action → explicit confirm).

**DATABASE CHANGES:** none (uses `reports.output_target`).

**BACKEND CHANGES:** extend `google_sheets` with `write_table`/`create_tab`;
report worker honours `output_target=google_sheet`.

**FRONTEND AND UX CHANGES:** target selector in report builder + status.

**FILES TO CHANGE:** `backend/app/integrations/google_sheets.py`,
`backend/app/workers/tasks/reports.py`, `backend/app/services/report_service.py`,
`frontend/components/workspace-app.tsx`.

**DEVELOPMENT TASKS:** 1) write_table/create_tab; 2) worker branch; 3) UI; 4) tests
(mock Sheets).

**TESTING CHECKLIST:** export creates/updates tab; input columns untouched; large
report chunked within API limits; SA‑permission error surfaced clearly; confirm
prompt before send.

---

### FEATURE 20 — Audit Logs and History Tracking

**FEATURE GOAL:** Comprehensive, queryable audit/activity trail for all Phase‑8
mutations (settings, scoring, mappings, deletes, competitor actions).

**CURRENT PROJECT AREA AFFECTED:** `audit_logs` + `audit_service.record()`
(already exist; under‑used).

**USER ROLES AFFECTED:** Admin/Manager (view, per `VIEW_AUDIT_LOGS`).

**BUSINESS LOGIC:** `✅` every create/update/delete/override/export records an audit
row with before/after + correlation id + actor; surface a viewer UI (the audit API
exists but has **no UI** today).

**DATABASE CHANGES:** none (reuse `audit_logs`); ensure new services call
`audit_service.record`.

**BACKEND CHANGES:** add `record()` calls across new services; ensure
`GET /audit-logs` filters (entity, actor, date).

**FRONTEND AND UX CHANGES:** Audit viewer (filter + diff display) — new desk.

**FILES TO CHANGE:** `backend/app/services/audit_service.py` (filters),
`backend/app/api/v1/settings.py` (audit endpoint exists), all new services,
`frontend/components/workspace-app.tsx` (+ `AuditDesk`).

**DEVELOPMENT TASKS:** 1) standardise record() calls; 2) audit query filters;
3) viewer UI; 4) tests.

**TESTING CHECKLIST:** each mutation writes an audit row; before/after correct;
filters work; permission gating; retention respected (`RETENTION_AUDIT_DAYS`).

---

## 11A. Dynamic Filtration & Reporting — Universal Integration (cross‑cutting, MANDATORY)

> **Non‑negotiable rule for Phase 8:** *Every* new field, entity, metric, status,
> category, score, domain, user/code, link type, DA value, competitor attribute,
> and date introduced by F1–F20 must be a **first‑class dynamic dimension** that is
> simultaneously **filterable, facetable (live counts), group‑by/pivotable,
> sortable, a selectable report column, and a report filter** — across both the
> Analytics surface and the Reports surface, for both company‑wide and
> project‑scoped views. **Nothing is allowed to exist that you cannot filter on or
> put in a report.** This section defines the single mechanism that guarantees it.

### 11A.1 The current gap (why things would otherwise be missed)

- `services/analytics_service.py` holds a **whitelist** of filters/facets/group‑by
  dimensions (one map).
- `workers/tasks/reports.py:_apply_backlink_filters()` holds a **second, parallel**
  copy of the filter logic, and `_BACKLINK_HEADERS`/`_HISTORY_HEADERS` are
  **hardcoded column lists**.
- The Reports builder UI pulls facet options from analytics, but the report's
  actual columns are fixed in the worker.

→ Three sources of truth that must be kept in sync by hand. Any new dimension added
to one but not the others is "missed." **This is the root cause to eliminate.**

### 11A.2 The fix — one Dimension Registry, many consumers

Introduce a **single dimension registry** (`services/dimensions/` or extend
`analytics_service`) that is the **only** place a dimension is declared. Every
consumer reads from it:

```
                         ┌─────────────────────────────┐
                         │   DIMENSION REGISTRY         │  one declaration per field
                         │   (key, label, sql expr,     │
                         │    type, ops, facet?, group?, │
                         │    sort?, report_col?, join,  │
                         │    value-source, ui-control,  │
                         │    permission, entity)        │
                         └───────────────┬─────────────┘
        ┌──────────────┬──────────────┬──┴───────────┬──────────────┬─────────────┐
        ▼              ▼              ▼               ▼              ▼             ▼
   Filter engine   Facet engine   Group‑by/pivot  Report filters  Report columns  Frontend UI
   (analytics +    (live counts)  (analytics +    (worker reuses  (dynamic column (auto‑renders
    reports share)                 reports)        SAME filters)   picker)         controls)
```

**Each dimension descriptor declares (the contract):**

| Attribute | Meaning |
|---|---|
| `key` | stable id, e.g. `link_type`, `source_da_band`, `competitor_category` |
| `label` | human label for UI + report header |
| `entity` | which engine it belongs to: `backlink` \| `source_domain` \| `competitor` \| `history` |
| `expr` / `column` | the parameterized SQL column/expression (never raw user input) |
| `join` | optional join needed (e.g. `source_domains`, `domain_authority_results`, `user_employee_mappings`) |
| `value_kind` | `enum` \| `text` \| `numeric` \| `numeric_band` \| `date` \| `boolean` \| `fk` |
| `operators` | allowed ops: `eq, in, not_in, range/between, contains, is_null, gte, lte` |
| `facetable` | show live connected counts? |
| `groupable` | usable as a pivot/group‑by? |
| `sortable` | usable as a sort key? |
| `report_column` | can appear as a report column? `default_in_report?` |
| `value_source` | where dropdown options come from (enum values, distinct query, facet, catalog table) |
| `ui_control` | `select` \| `multiselect` \| `range` \| `daterange` \| `toggle` \| `search` |
| `permission` / `scope` | visibility (e.g. cost/DA only for Manager+; respect project scope) |

**Result:** adding a Phase‑8 field = **add one descriptor**. It instantly becomes a
filter, a facet, a group‑by, a sortable column, a report filter, **and** a report
column, with the correct UI control — in both Analytics and Reports. `❓K` (confirm
this registry‑driven approach; it keeps the SQL‑injection‑safe whitelist while
making it DRY and dynamic).

### 11A.3 Dynamic filter capabilities (all entities)

- **Combinable filters:** AND across dimensions; `in/not_in` for multi‑select;
  `range/between` for numeric (score, DA) and dates; `contains` for text;
  `is_null` for "unchecked/unmapped/unknown". `🟦` Optional OR groups (confirm `❓K`).
- **Connected facets:** each dimension returns live counts given the *other* active
  filters (existing analytics behavior, extended to every new dimension).
- **Saved filter sets:** named, reusable filter combinations (per‑user or shared
  workspace‑wide) → `saved_filters` table. Used by Analytics, Reports, and the
  Competitor/Off‑page board. `❓L` (scope: per‑user vs shared).
- **Scope aware:** the project scope switch (`""`=company) and RBAC
  `allowed_project_ids` apply to every dimension automatically via the registry.

### 11A.4 Dynamic report capabilities

- **Build from any filter:** a report is generated from any ad‑hoc or saved filter
  set — identical filter semantics to Analytics (same registry, no second copy).
- **Dynamic column selection:** the report builder offers a **column picker** of
  every `report_column` dimension (with sensible defaults per report type); the
  worker builds headers + rows from the chosen set instead of a fixed list.
- **Group‑by / pivot reports:** a report can be a pivot (e.g. "links by link_type ×
  status", "opportunities by source_domain × DA band") using the same group‑by
  engine.
- **True frozen snapshots:** a generated report stores `{filter_set, column_set,
  group_by, scoring_rule_version, generated_at}` + the frozen rows
  (`report_snapshots`, §10.6) so re‑opening it always shows what it showed then —
  regardless of later data/scoring changes (answers `❓C`).
- **Report templates:** save a report definition (type + filters + columns +
  schedule) for one‑click / recurring runs (recurring delivery is Phase 9, but the
  **template** is defined here).
- **Every export path:** CSV / XLSX / PDF (existing worker) **and** Google Sheets
  (F19) work for **all** report types and column sets.
- **New report types (each fully filterable + column‑dynamic):**
  `SOURCE_DOMAIN_SUMMARY`, `LINK_TYPE_SUMMARY`, `USER_PERFORMANCE` (by employee
  code / app user), `SCORING_AUDIT` (which rule version scored what),
  `EXISTING_VS_NEW_DOMAINS`, `COMPETITOR_OPPORTUNITY` — alongside the existing
  CLIENT / CAMPAIGN / VENDOR / FAILED_LINKS / MONTHLY_QA / CHANGE_HISTORY.

### 11A.5 Master Integration Matrix (every Phase‑8 dimension)

> Legend: F=filter ✓, Fc=facet ✓, G=group‑by ✓, S=sort ✓, RC=report column ✓,
> RF=report filter ✓. All also flow to the Analytics UI + Report builder. Unless
> noted, scope = both company & project, both entities’ engines respect RBAC.

**Backlink‑entity dimensions (extend the existing backlink filter/report engine):**

| Dimension (key) | Source | F | Fc | G | S | RC | RF | UI control |
|---|---|---|---|---|---|---|---|---|
| `project_main_domain` | project_domains.domain | ✓ | ✓ | ✓ | – | ✓ | ✓ | multiselect |
| `link_type` (catalog) | link_types.id/name (replaces free‑text) | ✓ | ✓ | ✓ | – | ✓ | ✓ | multiselect+create |
| `employee_code` | employee_codes.code | ✓ | ✓ | ✓ | – | ✓ | ✓ | multiselect |
| `assigned_user` (app user) | user_employee_mappings→users | ✓ | ✓ | ✓ | – | ✓ | ✓ | multiselect |
| `assigned_user_label` (raw sheet) | backlink.assigned_user_label | ✓ | ✓ | ✓ | – | ✓ | ✓ | multiselect |
| `scoring_rule_version` | crawl_results.scoring_rule_version_id | ✓ | ✓ | ✓ | – | ✓ | ✓ | select |
| `score` / `score_band` | backlink.score / band | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | range+select |
| `grade_band` | derived | ✓ | ✓ | ✓ | – | ✓ | ✓ | multiselect |
| `dofollow` (bool) | current_rel | ✓ | ✓ | ✓ | – | ✓ | ✓ | toggle |
| `indexed` (bool/3‑state) | index_status | ✓ | ✓ | ✓ | – | ✓ | ✓ | select |
| `http_status` / `http_band` | backlink.http_status | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | range+select |
| `crawl_success` | derived | ✓ | ✓ | ✓ | – | ✓ | ✓ | toggle |
| `duplicate_status` | backlink.duplicate_status | ✓ | ✓ | ✓ | – | ✓ | ✓ | select |
| `sheet_tab` / `sheet_source` | google_sheet_project_tabs | ✓ | ✓ | ✓ | – | ✓ | ✓ | multiselect |
| `source_domain` (catalog) | source_domains.id (replaces string) | ✓ | ✓ | ✓ | – | ✓ | ✓ | search+select |
| `source_da` / `source_da_band` | domain_authority_results.da (join) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | range+band |
| `source_spam_score` | DA join | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | range |
| `placement_date`,`last_checked`,`index_checked`,`created` | date cols | ✓ | – | ✓ | ✓ | ✓ | ✓ | daterange |
| `is_deleted` (soft‑delete) | deleted_at | ✓ | – | – | – | – | ✓ | toggle (Admin) |

**Source‑domain engine (NEW parallel engine — same registry mechanism):**

| Dimension | F | Fc | G | S | RC | RF |
|---|---|---|---|---|---|---|
| `domain_key`, `grouping`(registrable/platform), `backlink_count`, `indexed_pct`, `dofollow_count`, `duplicate_count`, `avg_score`, `da/da_band`, `pa`, `spam`, `global_rank`, `monthly_visits`, `link_type_distribution`, `project_count`, `user_count`, `last_recomputed_at` | ✓ | ✓ (cat.) | ✓ | ✓ | ✓ | ✓ |

**Competitor engine (NEW parallel engine — physically separate tables):**

| Dimension | F | Fc | G | S | RC | RF |
|---|---|---|---|---|---|---|
| `competitor_sheet`, `comparison_category`(existing/new/already_used/needs_review), `qa_category` (F17 enum), `opportunity_score`/`band`, `link_type`+`confidence`+`categorization_source`, `competitor_da`/`band`, `indexed_pct`, `url_count`, `opportunity_status`(open/accepted/in_progress/done), `assigned_offpage_user`, `is_new_domain`(bool), `our_link_count` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

### 11A.6 Cross‑entity / relational filtering (the connections that are usually missed)

The registry's `join` attribute enables filters that **span entities** — these must
all work:
- Filter **backlinks** by **source‑domain DA band** (join `source_domains` →
  `domain_authority_results`).
- Filter/group **backlinks** by **employee code → mapped app user** (join
  `user_employee_mappings`).
- Filter **backlinks** by **scoring rule version** / by **link‑type scoring
  profile**.
- Filter **backlinks** by **project main domain** (join `project_domains`).
- Filter **competitor opportunities** by **whether we already have links from that
  source domain** (join our `source_domains`) and by **our link type for it**.
- Filter **source domains** by **link‑type distribution** (e.g. "domains we use only
  for Profile").

### 11A.7 Files to change (consolidated for the filtration/report unification)

- `backend/app/services/analytics_service.py` → refactor its map into the shared
  **dimension registry** (`backend/app/services/dimensions/registry.py` + per‑entity
  descriptor modules).
- `backend/app/workers/tasks/reports.py` → **delete** `_apply_backlink_filters`’
  duplication; call the **shared** filter builder; build columns dynamically from
  the selected `report_column` dimensions instead of `_BACKLINK_HEADERS`.
- `backend/app/services/report_service.py` + `schemas/report.py` → accept
  `column_set`, `group_by`, `filter_set_id` (or inline filters); store them frozen.
- `backend/app/api/v1/analytics.py` + new `reports`/`source_domains`/`competitors`
  endpoints → expose `GET /dimensions?entity=…` so the **UI auto‑renders controls**.
- New `saved_filters` model + endpoints; new report‑template support.
- `frontend/components/workspace-app.tsx` (AnalyticsDesk + ReportsDesk + new desks)
  → render filter controls and the report column picker **from the dimensions
  endpoint**, not hardcoded lists.

### 11A.8 Development tasks

1. Build the dimension registry + descriptor type; port existing dimensions into
   it (no behavior change → regression‑safe).
2. Make analytics filter/facet/group‑by read from the registry.
3. Make the report worker reuse the **same** filter builder + dynamic columns.
4. Add `GET /dimensions` (per entity) for the UI.
5. Add `saved_filters` + report templates.
6. As each feature F1–F20 lands, it **adds its descriptors** (definition of done:
   no feature is "done" until its fields appear in filter + facet + group‑by +
   report column + report filter, verified by a test).
7. Build the source‑domain and competitor parallel engines on the same registry.

### 11A.9 Testing (filtration/report integration — gating)

- **Parity test:** every registered dimension is filterable in Analytics **and**
  produces the identical result set when used as a report filter (no drift).
- **Coverage test:** automated assertion that **every** new Phase‑8 field has a
  registry descriptor (fail CI if a model column tagged "reportable" lacks one).
- Facet counts correct under combined filters; group‑by pivots on each dimension;
  sort on each sortable dimension.
- Dynamic column picker: report renders exactly the chosen columns, in order, in
  CSV/XLSX/PDF/Sheets.
- Cross‑entity joins (DA band on backlinks, employee→user, competitor vs our
  domains) return correct rows.
- Saved filter reused across Analytics + Reports yields identical scope.
- Frozen snapshot: a report’s filter/column/rule‑version set is preserved and the
  rows don’t change after later data/scoring changes.
- Scope + RBAC applied to every dimension (project scope, restricted columns).
- Large‑volume performance for filter+facet+group‑by over ~1–2M rows (indexes back
  every filterable/sortable dimension).

> **Definition of Done update (applies to ALL of F1–F20):** a feature is not
> complete until each of its user‑meaningful fields is (a) in the dimension
> registry, (b) usable as a filter + facet + group‑by + sort where sensible,
> (c) selectable as a report column, (d) usable as a report filter, and (e) covered
> by the parity + coverage tests above. This single rule is what guarantees
> "not a single thing missed to integrate or connect with Filtration and Reports."

---

## 12. Testing Strategy

**Framework:** existing `pytest` suite (87 tests today, run on the server in
`backend/venv`). Keep the pattern: **pure‑logic unit tests** (no network/DB) +
**service tests** (DB fixtures) + **API tests**. External calls (Sheets, Moz)
**mocked** — never hit live providers in tests.

**Per‑area checklists** (consolidated from each feature):

- **Project settings / main domain:** validation, primary uniqueness, audit on
  change, matching authority (flagged), history preservation.
- **Main domain update:** re‑match/re‑score path creates new results, leaves old
  intact.
- **User/employee‑code mapping:** uniqueness, reassignment history, sheet‑label
  reconciliation suggestions, report grouping.
- **Link‑type sub‑sheet detection:** tab enumeration, gid‑stable rename, add/delete
  drift, legacy single‑tab compatibility.
- **Sub‑sheet checkbox selection:** import/QA/active flags honoured; link‑type
  applied; create‑new‑type.
- **Global scoring:** Admin‑only; baseline default; versioning.
- **Project scoring override:** fallback order; version pinning; preview accuracy.
- **Score calculation:** deterministic; normalisation; hard‑fail rules;
  golden‑case fixtures; performance.
- **Source URL normalisation:** reuse existing `test_normalize.py`; add
  platform‑host cases (`❓E`).
- **Source main‑domain extraction:** grouping, invalid exclusion, backfill,
  rollup freshness.
- **Competitor upload:** CSV/XLSX/Sheet, partial errors, isolation from project
  links, multiple sheets.
- **Competitor validation:** required column, auto‑map, unknown columns preserved.
- **Existing vs new comparison:** detection accuracy, counts, idempotent re‑run.
- **Auto link‑type categorisation:** single/ambiguous/unknown, override, confidence.
- **Ambiguous categorisation:** candidates stored, surfaced in review queue.
- **DA API integration:** mocked success/failure/quota, cache hit, TTL refresh,
  history append, non‑blocking failure.
- **DA cache:** global key reuse (`❓G`), no per‑tenant refetch.
- **Competitor reports:** ranking, grouping, frozen snapshot immutability, formats.
- **Google Sheets export:** tab create/update, input columns untouched, chunking,
  SA‑permission error, confirm prompt.
- **Delete confirmation:** preflight counts, type‑to‑confirm, audit.
- **Soft delete:** hidden but preserved, restore in window, purge after window.
- **Audit logs:** every mutation logged, before/after, filters, retention.
- **Permission checks:** every new endpoint gated by the right `Permission`.
- **Large data volume:** source‑domain analytics, competitor comparison, reports on
  ~1–2M backlinks (use seeded volume fixtures).
- **Async job failure & retry:** scoring re‑run, DA fetch, competitor import —
  idempotency, `acks_late`, retry/backoff, partial‑failure isolation.

**Regression:** the existing 87 tests must stay green at every sub‑phase boundary;
add a CI gate `venv/bin/pytest -q` on the server before each deploy.

---

## 13. Risk, Security, and Scalability Notes

**Highest risks (design‑gated):**
1. **Scoring re‑architecture (F3/F4/F8).** Changing how scores compute can shift
   every verdict. Mitigate: keep checks/evidence unchanged; pin `rule_version` on
   each result; never mutate history; ship behind a flag; golden‑case tests;
   explicit, audited re‑score action. **Do not start before `❓B`/`❓C`.**
2. **Main‑domain matching semantics (F1).** Could change pass/fail for existing
   links. Mitigate: feature flag, backfill plan, `❓A`.
3. **Sheet sub‑sheet migration (F5/F6).** Relaxing `sheet_sources` uniqueness +
   moving to per‑tab state risks orphaning data. Mitigate: additive migration, gid
   keys, never delete imported links on tab loss.

**Security (honor existing golden rules):**
- All new provider keys (Moz/RapidAPI) **env‑only** via `config.py`; if runtime
  config is wanted, use the encrypted `settings` table (`is_secret`) — never
  hardcode, never commit. Tell the user to rotate any key pasted in chat.
- Competitor uploads are **untrusted input**: validate, size‑cap, never crawl
  competitor URLs without the existing **SSRF guard**; treat competitor source
  URLs as data, not fetch targets, unless QA is explicitly requested.
- Google Sheets export is **outward‑facing** — require explicit confirm; SA stays
  least‑privilege (Editor only where write‑back is on).
- Every new endpoint behind the correct RBAC `Permission`; new perms
  `MANAGE_SCORING`, `EDIT_PROJECT_SCORING`, `MANAGE_COMPETITORS` (Admin/Manager).
- Soft delete + audit gives an undo/forensic trail; prod destructive SQL stays
  gated (no manual mutations).

**Scalability (target ~1–2M backlinks):**
- **Aggregates over scans:** source‑domain + competitor analytics read **rollup**
  tables refreshed by scheduled jobs, not live `COUNT(*)` over millions of rows.
- **Keyset pagination** (existing pattern) for all new large grids.
- **DA as a global cache** keyed by domain (not per tenant) — `forbes.com` is fetched
  once. Staggered fetch + TTL + backoff to respect quotas/cost.
- **Competitor data isolated** in its own tables → never bloats the hot
  `backlink_records` path; partition `competitor_backlinks`/`domain_authority_
  history` by month **only if** they grow into the millions.
- **Rollup freshness:** learn from the LinkIdentity rollup gap (§2.3#4) — use a
  scheduled recompute (idempotent) and/or DB triggers; expose `last_recomputed_at`.
- **Background jobs:** reuse the dead `qa` queue for re‑scoring; isolate heavy
  external calls (DA, competitor import) on their own queues so a flood doesn't
  starve crawling.
- **Frontend:** split new desks out of the 2,210‑line `workspace-app.tsx` to keep
  bundle/maintenance sane.

**Ops:** investigate the `api` process's ~300 restarts before adding heavy
endpoints; confirm real storage backend (MinIO vs local) before report‑snapshot
work; one migration per sub‑phase for reviewable, reversible deploys.

---

## 14. Final Recommended Roadmap

### 14.1 Best recommended development sequence
1. **8.1 Foundations** — F20 audit scaffolding → F7 safe‑delete framework →
   F1 project settings + main domain → F2 users/employee codes.
2. **8.2 Link‑type & sheets** — F5 sub‑sheet detection → F6 tab selection → finalize
   `link_types` catalog (backfill from existing data).
3. **8.3 Scoring** — (after `❓B/❓C`) F8 parameter engine → F4 global → F3 project
   override → re‑score job.
4. **8.4 Source‑domain intel** — F9 aggregate → F16 DA → F10 dashboard.
5. **8.5 Competitor/market** — F11 upload → F12 map/validate → F13 compare →
   F14 auto‑type → F17 QA categorise → F15 reports → F18 off‑page board →
   F19 Sheets export.

### 14.2 Minimum Viable Phase (ship first, lowest risk, high value)
**MVP = 8.1 + 8.2 + F9 + F16 + F10** (foundations, real link types from sub‑sheets,
source‑domain analytics with DA). Delivers: configurable project settings, true
link‑type catalog, safe deletes, and a source‑domain intelligence dashboard —
**without** touching the scoring engine or building the competitor subsystem.
Each piece is independently deployable and reversible.

### 14.3 Full future roadmap (beyond Phase 8)
- **Phase 9:** scheduled report delivery (email/Sheets digest) + finish alert
  digest/quiet‑hours + in‑app admin for integrations/audit.
- **Phase 10:** client portal + read‑only scoped API tokens (clients see their own
  backlinks/opportunities).
- **Phase 11:** trend/time‑series analytics (DA over time, indexed% over time),
  competitor tracking deltas (new links competitors gained since last upload).
- **Phase 12:** ops — GitHub remote + one‑command deploy + Postgres PITR backups;
  optional Playwright render pool for SPA sources.

### 14.4 Questions that MUST be answered before development starts
> (Restated from §3 — development of the dependent feature is blocked until each is
> resolved.)

1. **(A) Main domain:** one or many per project? Does it **replace** or
   **supplement** per‑row target for matching? → blocks F1, F9, F13.
2. **(B) Scoring model:** weighted‑parameter (B1) or configurable severity (B2)? Do
   status bands become configurable? → blocks F3/F4/F8.
3. **(C) Freeze semantics:** re‑score history on rule change, or keep versioned and
   frozen? → blocks F8/F15/F19 + report design.
4. **(D) Sheet layout:** are link types separate **tabs** or a **column**? Can you
   share a sample (anonymised) project spreadsheet? → blocks F5/F6.
5. **(E) Domain grouping:** registrable domain only, or platform‑host grouping for
   Web‑2.0 (`*.blogspot.com`, `medium.com/@user`)? → blocks F9, F13, F14.
6. **(F) Employee codes:** uniqueness scope; multiple codes per user; reassignment
   allowed? → blocks F2.
7. **(G) DA provider & budget:** which provider (Moz RapidAPI / Moz official /
   Similarweb) and monthly quota/cost ceiling? Global cache OK? → blocks F16.
8. **(H) Competitor sheets:** column format; file vs Google‑Sheet URL; export target
   tab behaviour? → blocks F11/F12/F19.
9. **(I) Delete policy:** which entities soft‑delete; restore window length; project
   delete = archive‑keep‑history vs delete‑all? → blocks F7.
10. **(J) Permissions:** Admin‑only global scoring? Manager scope for project
    scoring/competitors? → blocks F3/F4 RBAC.
11. **(Ops) Storage backend:** is prod really MinIO (PM2 shows it) vs `local` in
    docs? → blocks F15 report snapshots / F11 uploads.
12. **(K) Filtration model:** confirm the **registry‑driven dynamic dimension**
    approach (§11A) — one declaration drives filters + facets + group‑by + report
    columns + report filters + UI, keeping the injection‑safe whitelist. Do you
    also want **OR filter groups** (not just AND)? → blocks the §11A unification
    that every feature depends on.
13. **(L) Saved filters / report templates:** scope = **per‑user** or **shared
    workspace‑wide** (or both)? → blocks `saved_filters` + report templates.

> **Note:** §11A makes "everything filterable + reportable" a **definition‑of‑done
> rule** for every feature F1–F20. Confirming **K** early is high‑leverage: it
> removes the analytics/report filter duplication that currently exists and ensures
> no new field is ever disconnected from Filtration or Reports.

---

### Document status
This is a **planning document only** — no production code was written. Items are
tagged `✅ CONFIRMED` / `🟦 RECOMMENDED` / `❓ NEEDS CONFIRMATION`. Once the 11
questions above are answered, sub‑phase **8.1** can begin immediately (it has no
blocking confirmations except the soft‑delete scope **I**, which only affects F7's
restore window, not its structure).

