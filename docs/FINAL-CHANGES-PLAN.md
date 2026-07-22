# Final-changes program — 13 areas (2026-07-22 brief)

Owner's last pre-delivery batch. Implemented in tranches, each deployed +
committed. Anchors from the `final-13-map` workflow investigation.

## Tranche F1 — quick wins (one deploy)
- **#8 Viewer exports + default range**: remove every export control from
  viewer-reachable surfaces (My Work, My Dashboard/selfView, My recent links,
  Opportunities, Guidance); viewer My Dashboard default window → last 30 days.
- **#12 Target vs Done chart on viewer Overview**: render the SAME plan_weekly
  chart the admin user-dashboard shows (gray target bar + purple done bar,
  Day/Week/Month gran) on My Dashboard → Overview (selfView).
- **#9 Opportunities explainer**: collapsible info panel on `myopps` (what the
  domains are, where they come from, what statuses/scores mean, how to use).
- **#10 Request Leave in the leave tab**: the leave-management surface gets an
  inline "Request leave" (users) next to the approvals list (admins) — nobody
  hunts for it in another desk.
- **#2 User Dashboards white-label**: active-only by default with a neutral
  **Show all** toggle (no "laid off" wording anywhere in the default view; no
  "N active · M laid off" summary); list ⇄ grid view toggle; avatars where a
  label maps to an account; **global setting** (Settings → Company) to
  show/hide profile photos system-wide (workspace Setting `display_prefs`).
- **#4 Backlinks toolbar UX**: actions row visually separated from the filters
  row; "Scoring guide" becomes a right-aligned info icon (not a primary
  action button).

## Tranche F2 — Tasks & Calendar nav restructure (#1) + completion math (#11)
- Sidebar: Tasks & Calendar expands into sub-items (same pattern as My
  Dashboard's DASH_SECTIONS): **Planner** (week-by-week), **By user**,
  **By project**, **Calendar**, **Working days**, **Leave** (separate tab).
- REMOVE the "Productivity (links per hour)" section from the Tasks desk
  (it stays in Settings → QA & rates — single home).
- **Completion math**: config knob `TASK_COMPLETION_START_DATE = 2026-07-27`;
  all completion METRICS (plan stats, plan_weekly, week strips, dashboards,
  reports) clamp their window start to the cutoff — data before it is ignored.
  Days with no assignment already produce no rows (verify + test); rest days
  never reduce %.

## Tranche F3 — Batch failure reasons (#5) + Team redesign (#6)
- **#5**: "Problems in this run" panel on batch details for partial/failed —
  top reasons synthesized from batch error + error/warning logs + failed-item
  errors (grouped, with counts); list rows get a one-line reason hint.
- **#6**: full Team page restructure: overview header, clean member cards/
  table, grouped actions, scoping folded in, consistent section rhythm across
  the four tabs.

## Tranche F4 — Security (#3)
- **IP-change session guard**: refresh-token rows already carry the issuing
  ip; new rules toggle `bind_sessions` — on rotate, an IP mismatch revokes the
  session (audited) → user must sign in again.
- **IP rules extensions**: per-entry **remarks** (`ip_notes` map — backward
  compatible), **team-based access** (`team_overrides` keyed by TeamLead: the
  lead's scoped people resolve via the employee mapping at login), keeping
  global + role + user (precedence: user > team > role > master).
- **Security log**: admin viewer in Settings → Security over audit_logs
  (login, failed login, logout, session revocations, security-settings
  changes) with time/user/IP/device columns + filters + load-more. Logout +
  session-revoke events recorded.

## Tranche F5 — Intern level (#7)
- `intern` added to the Role enum (native pg enum → ALTER TYPE migration) +
  RBAC row, Team invite/role dropdowns, nav gating.
- **Isolation by design — reuse the staging pipeline**: intern links are
  submitted from their own desk into `link_review` batches tagged
  `meta.intern_submission` and are **never imported** until an admin decides.
  QA runs with the existing isolated staged worker (verdicts in item payload
  only) → intern analytics/performance compute from THEIR batch items, so
  main analytics are untouched by default.
- Intern desk: paste/submit links (project-scoped), "My submissions" list with
  per-link verdicts + summary KPIs.
- **Promotion**: role change intern → viewer/member (existing changeRole).
- **Transfer control** (admin, per batch or per intern): keep separate
  (default) / partial (approve selected items) / full (approve all) — the
  existing approve pipeline IS the transfer; nothing automatic.

## Tranche F6 — Link-suggestion overhaul (#13)
- Extend the recommendations stack: search, filters (status/priority/project/
  user/task/date), sorting, multi-select, per-row reason, similar-domain view,
  dismiss / mark-used, task association; exports restricted to **CSV +
  plain-text only**.

## Cross-cutting
- Permissions verified per role incl. new intern; empty/loading/error states;
  no isolated one-off patterns — nav + info-panel + list/grid patterns reused.
