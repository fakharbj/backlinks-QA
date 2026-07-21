# Delivery-polish plan — pre-handoff enhancement batch (2026-07-22)

Owner brief: seven areas to finalize before delivering dashboards to the team.
Investigated 2026-07-22 (4 parallel deep-dives; anchors verified against code +
live prod DB). Implementation in tranches, each deployed + verified.

## T1 — Frontend quick wins (one deploy)

1. **Viewer nav: remove "Plans & calendar"** for viewer role only.
   Anchors: Sidebar injection `workspace-app.tsx:1877` (role in scope), MobileNav
   ~1949 (role prop available), UserDashboard section band 9995–10007 (filter on
   `selfView`), plus guard `section === "calendar"` content at 10375 for selfView.
2. **"New domains" cards clarity** (UserDashboard Overview 10050–10055).
   Semantics (performance_service 173–180): *project* = first-in-each-project
   (summed across projects → can exceed overall); *overall* = first-ever in the
   workspace. Redesign: one combined "New source domains" card with two labeled
   rows + plain-words explainer; rename to "First use in a project" vs
   "First use ever (workspace)".
3. **Dropdown clipping**: hero band `overflow-hidden` at 9878 clips SearchSelect
   menus (9944/9951 — the only clipped instances today). Fix: move the
   decorative wash into an inner absolute `overflow-hidden rounded-2xl` layer;
   outer keeps visible overflow. Sweep confirmed no other clipped dropdowns.
4. **My calendar page order**: move "This week" block (7054–7058) ABOVE
   `<MyTaskCalendar>` (7045). Add ‹ › week navigation to `UserWeekStrip`
   (9448–9532; internal monday state, header "This week — {label}" 9497).
5. **Tasks "By project" card**: cap list (~8) + "View all / Load more" (statGroups
   render 7541–7586; per-card shown-count keyed state). Keeps height aligned with
   the "By person" card.
6. **Planner edit visibility**: move the assign/edit form (8237–8331) into a
   modal overlay; `prefillForm` (7375–7391) opens it (drop scrollIntoView). All
   deps in TasksDesk scope. "Assign work" button opens the same modal.
7. **Status colors**: WARNING (Needs improvement) stays amber; NEEDS_MANUAL_REVIEW
   (Needs review) becomes **plum** everywhere it's currently amber: Status pill
   (20460 → new `.pill-review` in globals.css using `--plum`), Health-mix
   StackedBar 2394, UserDashboard KPI row 10075 (+ QA pending 10077 → muted).
   Overview/Analytics already use plum — this unifies.
8. **Filter search (Source domain / User "no matches")**: root cause = facets
   hard LIMIT 50 (analytics_service.py:384) + client-only search in
   FilterMultiSelect (20718). Fix: (a) User filter options → full
   `/workforce/labels` list; (b) FilterMultiSelect gains optional async
   `onSearch` prop — source-domain instances (Backlinks 3529, Analytics, Reports)
   wire it to `GET /source-domains?search=&limit=50` (endpoint exists) and merge
   results; (c) `allowCustom` on both as fallback. Link type/status/rel/etc are
   full/static lists — unaffected.

## T2 — Non-working-day correctness + user self-settings (OWNER-ANSWERED 2026-07-22)

- **Saturday: owner says NO blanket change** — Saturdays stay working by
  default; only days **manually set off in the working-days calendar** count as
  non-working. The default rule (Sun off, per-date overrides) stays. The one
  real gap to fix: weekly overbooked (workforce.py `weekly_capacity`,
  week_over at :594/:603) sums assigned hours INCLUDING manually-off days —
  exclude non-working days' assigned hours from the week_over calculation so a
  task on a manually-off day never causes "overbooked". (Day-level excusal &
  capacity-0 already work everywhere else — verified.)
- **User self-settings (owner: "just user photo and reset option only")**:
  a small "My settings" area (My Work): (a) upload own profile photo (data-URI,
  ≤300KB, shown in My Work header, Team members, User Dashboards list/header),
  (b) change own password (current + new). Needs: users.avatar column (or
  Setting KV), change-password endpoint (check existing /auth surface).

## T3 — Batches: parent-only list, children inside, pagination

- Child batches get `meta.parent_batch_id` (JSONB — no schema migration): write
  at sheet_sync_service.py:447–451 (parent uuid in scope).
- Alembic data migration backfills existing children (match parent meta
  `p:<sheet_source_id>` keys + started_at within parent window).
- `GET /batches`: add `offset` param (pagination) + exclude-children default
  (`meta->>'parent_batch_id' IS NULL` unless `parent=<id>` or `include_children`).
- BatchDetails (sheet_sync_all): real "Child syncs" section listing children via
  `/batches?parent=<id>` (status/progress/counters, click-through to the child's
  own details = project/sheet/link details, logs, errors). Replaces the
  heuristic bulkChildren match (11512–11519, 12039–12046).
- Frontend list: Load more (offset), sorted latest-first (already server-side).
- Single-project manual syncs (no parent) remain one visible entry. SheetsDesk
  bulk card reads parent meta only — unaffected.

## T4 — Competitors: expand-in-place

- Backend: `competitor` param on `GET /competitors/domains` (EXISTS against
  competitor_backlinks restricted to the competitor's sheet_ids — list_parents
  already computes them; service :384–465).
- Frontend: "Competitor source domains" card hidden by default; expanded
  competitor row gains a **Domains** sub-tab (full grid, competitor-scoped,
  reusing the existing grid + metric-check/export/dismiss actions) alongside the
  existing uploads + links panel. A toolbar toggle "All source domains" restores
  the global grid.

## T5 — Team desk redesign (UI only, same logic/endpoints)

Pain points (mapped): 4-button actions cell per member row; window.prompt-based
edit-login/reset-password; N+1 MemberProjectsCell queries; duplicated scoping
card; two merge entry points; Gmail assignments listed twice; two deactivation
concepts on different tabs.
Redesign: members table slims to Member/Role/Projects/Status/Last login + one
**actions menu** (⋯) per row; proper modal for Edit login / Reset password
(replaces prompts); "Team scoping" folds into the member row (managers/qa get a
"Scope" action); Employees tab keeps both merge paths but visually unified;
Gmail tab drops per-account chips duplication (table stays the source of truth).
No endpoint changes.

## T6 — QA scoring change + retroactive rescore (prod data change — owner-authorized in brief)

Verified prod state: ONE global rule-set v1 (0037 reseed), bands {fail<30,
warn<80}, no overrides; 45,306 records (12,687 PASS / 11,829 WARNING / 8,600
FAIL / 8,025 REVIEW / 3,128 UNKNOWN / 1,037 PENDING).

1. **Zero the five deductions** — new global rule-set **v2** (idempotent alembic
   data migration calling the same insert path as save_version): copy v1 rules,
   set `anchor_match.changed=0`, `canonical.missing=0`,
   `link_placement.{header,footer,sidebar,nav}=0`, `link_rel.sponsored=0`
   (covers REL-03 + LNK-15). Bands unchanged.
2. **PQ-06 (spam keywords)**: NOT rule-mapped → zero via code:
   add "PQ-06" to `_UNSCORED_CODES` (qa/scoring.py:35). (Severity stays MEDIUM
   for display; delta = 0. Works retroactively because rescore replays stored
   snapshots through score_issues.)
3. **Status logic**: classification.py:96 — drop the `Severity.HIGH/MEDIUM`
   terms; WARNING purely `score < warn_below` (80). Order of precedence
   (critical→FAIL, review, transient, fail_below) unchanged. Result: score ≥ 80
   → PASS even with Sponsored/etc deductions; "Needs improvement" strictly < 80.
4. **Staging parity**: staged-import QA (workers/tasks/staging.py:195) and QA
   lab evaluate without a ruleset — classification fix reaches them; pass the
   resolved ruleset in staging so preview scores match post-approve.
5. **Tests**: update/verify test_spam_scoring (severity assertions unaffected via
   _UNSCORED_CODES route), test_checks nofollow→WARNING (survives: 75 < 80),
   test_scoring_rules classify bands (score-only — fine). Full suite must pass.
6. **Retro-apply**: preview via rescore_service (transition counts) → report →
   apply per-project loop server-side (avoids one 44k-row transaction + gunicorn
   timeout; rescore() commits per call; RESCORED history events per changed row;
   scoring_rule_version_id restamped → auditable). Expect most of the 11,829
   WARNINGs to flip to PASS.

## Sequencing
T1 → T6 (scoring; highest business value, longest verification) → T3 → T4 → T5
→ T2 (after owner answers, can run any time). Each tranche: build, deploy,
verify live, commit.
