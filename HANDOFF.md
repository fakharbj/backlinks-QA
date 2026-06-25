# LinkSentinel — Full Handoff for the Next Claude Code

> **Read this first, top to bottom, before touching anything.** It is the single
> source of truth for what this system is, how every part connects, how it is
> deployed on the CloudPanel VPS, and what is and isn't done. Then skim
> `docs/DEVELOPMENT-PLAN.md` (the build plan) and `docs/FINAL-STATUS.md` (phase
> status). The repo is the source of truth for code; the live server mirrors the
> repo.

---

## 0. The 60-second orientation

- **What it is:** LinkSentinel is a production backlink-QA + crawling + Google-Sheets-ingest
  + ERP-analytics + reporting platform for an SEO agency. It pulls backlink lists
  (from pasted CSV or Google Sheets), crawls each source page, runs a QA engine
  (is the link present? dofollow/nofollow? indexed? duplicate? broken?), raises
  alerts/emails on regressions, and produces filtered, **versioned** reports.
- **Live URL:** **https://72.62.81.34.nip.io/** (CloudPanel-hosted VPS).
- **Stack:** FastAPI (async) + PostgreSQL 16 + Redis + Celery on the backend;
  Next.js 14 (App Router) on the frontend; PM2 process manager behind CloudPanel's
  nginx.
- **You deploy by:** `tar`-over-SSH of changed files → `npm run build` (frontend) /
  `alembic upgrade head` (backend migrations) → `pm2 restart`. Passwordless SSH as
  `root@72.62.81.34` is already set up. (See §7.)
- **Golden rules:** never hardcode secrets (env only); never commit `.env` or
  `service-account.json`; don't disable the SSRF guard; the user must rotate any
  key that was ever pasted in chat. (See §10.)

---

## 1. Architecture at a glance

```
                         ┌─────────────────────────────────────────────┐
  Browser ── HTTPS ─────►│ CloudPanel nginx (vhost: 72.62.81.34.nip.io) │
                         └───────────────┬─────────────────┬───────────┘
                                         │ /                │ /api/v1
                                         ▼                  ▼
                              Next.js frontend       FastAPI (gunicorn+uvicorn)
                              PM2: "frontend" :3000   PM2: "api" 127.0.0.1:8000
                                                            │
                          ┌─────────────────────────────────┼───────────────────┐
                          ▼                                  ▼                   ▼
                   PostgreSQL 16                        Redis                Celery
                   (db: linksentinel)            broker/result/redbeat   PM2: "worker"
                                                                         PM2: "beat" (RedBeat)
```

- **Backend = a modular monolith.** One FastAPI app (`app.main:app`) for the HTTP
  API; the *same* codebase runs as Celery workers for background jobs. They share
  models/services/config. There is no separate microservice.
- **`app.core.config.Settings`** (Pydantic `BaseSettings`) is the ONLY place that
  reads env. Nothing else touches `os.environ`. Read it to learn every tunable.
- **Frontend** is a single client component tree (`frontend/components/workspace-app.tsx`)
  talking to the API via `frontend/lib/api.ts`. TanStack Query for data fetching.

---

## 2. Repository layout

```
backlinks qa/                         ← repo root (git: branch main)
├── HANDOFF.md                        ← this file
├── backend/
│   ├── app/
│   │   ├── main.py                   ← FastAPI app factory, router mounts, /healthz /readyz /metrics
│   │   ├── core/
│   │   │   ├── config.py             ← ALL settings/env (read this to understand the system)
│   │   │   ├── logging.py            ← structlog JSON logging
│   │   │   └── security.py           ← JWT, password hashing
│   │   ├── api/v1/                    ← HTTP routers (auth, projects, backlinks, imports,
│   │   │                                dashboard, alerts, reports, sheets, index, analytics, team)
│   │   ├── services/                 ← business logic (one file per domain)
│   │   │   ├── auth_service.py        (login/register/rotate_refresh/logout)
│   │   │   ├── import_service.py      (CSV/paste ingest → backlinks)
│   │   │   ├── crawl_service.py       (enqueue + record crawl results)
│   │   │   ├── qa_service.py          (verdict computation)
│   │   │   ├── alert_service.py       (rules + built-in broken-link alerting/email)
│   │   │   ├── report_service.py      (create/list reports + VERSIONING logic)
│   │   │   ├── sheet_sync_service.py  (main sheet → project sheets → import; write-back)
│   │   │   ├── duplicate_service.py   (link identity + duplicate classification)
│   │   │   ├── index_service.py       (Google index check orchestration + dedup)
│   │   │   └── analytics_service.py   (whitelisted dynamic filter/facet/group-by engine)
│   │   ├── integrations/             ← external systems (network egress lives here)
│   │   │   ├── proxy.py               (IPRoyal Web Unblocker URL builder)
│   │   │   ├── google_sheets.py       (gspread + service account read/write)
│   │   │   ├── serp.py                (Google index check: serper.dev / CSE / proxy-scrape)
│   │   │   └── site_metrics.py        (Similarweb/Moz via RapidAPI — optional)
│   │   ├── crawler/                   ← fetch + parse (parse.py finds the link, rel, hidden, etc.)
│   │   ├── models/                    ← SQLAlchemy 2.0 models (Project, Backlink, CrawlResult,
│   │   │                                Report, AlertRule, SheetSource, LinkIdentity, IndexCheck …)
│   │   ├── schemas/                   ← Pydantic request/response models
│   │   ├── workers/                   ← Celery app + tasks/ (crawl, qa, alerts, reports, sheets,
│   │   │                                index, maintenance) + RedBeat schedule
│   │   └── db/                        ← engine/session, init_db (partition mgmt, retention drop)
│   ├── alembic/versions/             ← migrations 0001 … 0006 (apply with `alembic upgrade head`)
│   ├── tests/                        ← pytest (87 passing); pure-logic units + service tests
│   ├── scripts/                      ← diagnostics (test_proxy.py, test_sheets.py …)
│   ├── requirements.txt              ← pinned deps (Python 3.13-compatible; see §9 gotchas)
│   ├── service-account.json          ← Google SA creds (NOT in git; present on server only)
│   └── .env                          ← secrets/config (NOT in git; present on server only)
├── frontend/
│   ├── app/                          ← Next.js App Router (page.tsx renders <WorkspaceApp/>)
│   ├── components/workspace-app.tsx  ← the entire UI (tabs, dashboards, reports, analytics…)
│   ├── lib/api.ts                    ← API client + token manager (durable session, see §8)
│   └── package.json
├── deploy/ecosystem.config.js        ← PM2 process definitions (api/worker/beat/frontend)
└── docs/
    ├── DEVELOPMENT-PLAN.md            ← the phased build plan (0–7)
    └── FINAL-STATUS.md               ← what's delivered + recommendations
```

> Note: `backend/app.zip` shows as modified in git — it's a stale packaging
> artifact, ignore it / don't rely on it. Deploy from real files, not the zip.

---

## 3. The data pipeline (how a backlink flows through the system)

1. **Ingest.** A backlink row enters via (a) **paste/CSV import** (`/imports/paste`)
   or (b) **Google Sheets sync** (`/sheets/sync`). Both funnel through the same
   `import_service` pipeline → rows become `Backlink` records under a `Project`.
   - Required input columns: `source_url`, `target_url`; optional
     `expected_anchor_text`, `expected_rel`, `campaign`, `vendor`, `tags`, and a
     free-text **link type** + assigned **User** (employee).
2. **Crawl.** `crawl_service` enqueues each backlink to a sharded Celery queue
   (`crawl.http.0..3`). The crawler fetches the source page (HTTPS-first, real
   Chrome UA, robots-aware). If blocked (403/429/503) it retries as Googlebot and,
   if still blocked, **escalates through the IPRoyal proxy** (`PROXY_MODE=escalate`).
   If the link is absent from raw HTML and the page looks JS-driven, it can
   proxy-render. Result → `CrawlResult` (month-partitioned table).
3. **QA.** `qa_service` computes a verdict per link: link present? anchor match?
   `rel` (dofollow/nofollow/sponsored/ugc)? noindex/robots-blocked? canonical
   issue? broken? hidden via CSS? → an overall status **PASS / WARNING / FAIL /
   NEEDS_MANUAL_REVIEW** + a score.
4. **Index check.** `index_service` + `integrations/serp.py` ask Google whether the
   **exact source URL** is indexed (`site:<url>`). Deduped by source URL,
   re-checked every `INDEX_RECHECK_DAYS` (7). Verdicts: INDEXED / NOT_INDEXED /
   UNCERTAIN (any ambiguity is UNCERTAIN, never a false negative). Provider is
   **serper.dev** in prod (reliable JSON). See §6.
5. **Duplicate detection.** `duplicate_service` computes a sha256 identity key from
   **Source URL + Target Domain** and classifies UNIQUE / DUP_SAME_PROJECT /
   DUP_CROSS_PROJECT / DUP_CROSS_USER.
6. **Alerts.** Built-in (zero-config) alerting raises an in-app alert + emails the
   team when a link is broken/removed/errored, **re-notifies every
   `ALERT_RENOTIFY_HOURS`** while it stays broken, and sends one "recovered" note.
   Custom `AlertRule`s add thresholds/severities. Email needs SMTP_* set.
7. **Analytics.** `analytics_service` is a **whitelisted** dynamic query engine:
   filters + connected facets (with live counts) + group-by pivots. Adding a new
   dimension = editing one map in that file. Powers the Analytics tab AND the
   Reports filter bar.
8. **Reports.** `report_service` generates **frozen-snapshot, versioned** reports
   (XLSX/CSV/PDF) from the same filters. Each generate = a new version; the newest
   is `is_latest`. Columns include Assigned User, Employee Code, Link Type, Index
   Status, Duplicate. (See §8 for the UI.)
9. **Write-back (optional).** `/sheets/{id}/writeback` writes system result columns
   (LS Status / LS Score / LS Index / LS Duplicate / LS Checked) back into the
   project Google Sheet. The SA needs **Editor** on those sheets.

**Source of truth:** the **Sheet is input**, the **database is the results/source
of truth.** Never treat the sheet as authoritative for results.

---

## 4. Key product decisions (locked — do not relitigate)

- **Google Sheets model:** ONE global **main sheet** with two columns — `Project Name`
  + `Project Sheet URL` (plain URL to a separate per-project sheet). Each project
  sheet = one project. Auth via **service account** (share every sheet with the SA
  email). Column mapping is configurable.
- **Workspace model:** "One workspace (all together)."
- **Link types:** free text / flexible (not a fixed enum).
- **Index check:** "Exact source URL indexed" via Google `site:`; manual + weekly.
- **Duplicate rule:** Source URL + Target Domain.
- **Scale target:** ~1,000 project sheets × ~1,000 rows (~1–2M backlinks). History
  tables are month-partitioned; retention **drops partitions** (O(1)) instead of
  DELETE.
- **"User" field** = the assigned employee, linked to an app user where possible.
- **Report version** = a frozen snapshot at generation time.

---

## 5. Frontend UX structure (so you can find things in `workspace-app.tsx`)

- **Top nav tabs:** Overview · Analytics · Backlinks · Imports · Sheets · Alerts ·
  Reports · Team.
- **Project selector = a SCOPE SWITCH** (top-left). Default is **"🏢 All projects
  (company)"** → Overview/Backlinks/Reports run company-wide. Pick a project → they
  scope to it. (`Overview` shows "Company dashboard" vs "Project dashboard"
  heading.) **Imports** requires a specific project (it prompts otherwise).
- **Reports tab (recently redesigned for non-technical users):**
  - A 3-step **builder**: (1) what to report — plain-language report-type cards;
    (2) which links — scope chip + filter dropdowns (status/index/duplicate/user/
    link-type) driven by the analytics facets, with a live **"N links will be
    included"** count; (3) file type (Excel/CSV/PDF) + Generate.
  - **Versioning UI:** saved reports are grouped into **version stacks** per
    (type + project). Each card shows the project name + **"Latest · vN"**, the
    filters it used, and older versions collapsed under a "Show N older versions"
    toggle. Version numbers are derived from recency in the UI so they always read
    cleanly even for rows created before versioning existed (see §11 gotcha).
- **Session:** durable — see §8.

---

## 6. Integrations & how they're wired

| Integration | File | Prod state | Notes |
|---|---|---|---|
| **IPRoyal Web Unblocker** (proxy) | `integrations/proxy.py` | enabled, `escalate` mode | TLS verify OFF for proxied reqs (unblocker MITMs TLS). Only blocked pages use proxy bandwidth. Creds in `.env` (`IPROYAL_*`). |
| **Google Sheets** | `integrations/google_sheets.py` | enabled | gspread + `service-account.json` (path in `GOOGLE_SA_JSON_FILE`). Main sheet id + col names in `.env`. Read for sync, write for write-back. |
| **serper.dev** (index check SERP) | `integrations/serp.py` | enabled (`SERP_PROVIDER=serper`) | POST `google.serper.dev/search`, `X-API-KEY` header; indexed if `organic` non-empty. Free ~2,500 queries. Fallbacks: `google_cse`, `proxy_scrape`. |
| **RapidAPI Similarweb/Moz** (site metrics) | `integrations/site_metrics.py` | off by default | Authority/traffic for the SOURCE domain (can't be crawled). Per-domain cached. `RAPIDAPI_KEY` in `.env`. |
| **SMTP** (alert email) | used by `alert_service` | only if `SMTP_*` set | Built-in broken-link emails + recovered notices. |

The index-check verdict logic in `serp.py` is split into **pure functions**
(`classify_serp_html`, `parse_result_count`) so it's unit-tested without network.

---

## 7. Deployment — the CloudPanel VPS (read carefully)

### The server
- **Host / SSH:** `ssh root@72.62.81.34` — **passwordless key auth is already set
  up** from this machine. (The public domain is `72.62.81.34.nip.io`, a nip.io
  wildcard that resolves to the IP, so HTTPS works without a real DNS record.)
- **Panel:** **CloudPanel** manages the nginx vhost, the Let's Encrypt cert, and the
  PostgreSQL instance. The site lives under a CloudPanel "site user" `ls_user`.
- **Site root:** `/home/ls_user/htdocs/72.62.81.34.nip.io/`
  ```
  ├── backend/        (FastAPI + Celery; venv/ is the Python 3.13 virtualenv)
  ├── frontend/       (Next.js; built with `npm run build`, served by `npm start`)
  ├── deploy/         (ecosystem.config.js)
  ├── docs/
  ├── start-api.sh  start-beat.sh  start-frontend.sh   (legacy convenience scripts)
  ```
- **Python:** 3.13.5, venv at `backend/venv` (note: **`venv`**, not `.venv`).
- **nginx (CloudPanel vhost):** reverse-proxies `/` → frontend `127.0.0.1:3000`
  and `/api/v1` → backend `127.0.0.1:8000`. The frontend's `API_BASE` defaults to
  the relative `/api/v1`, so nginx does the routing. (Exact vhost config is managed
  in the CloudPanel UI / `/etc/nginx/...` — edit through CloudPanel.)

### PM2 processes (the runtime)
`pm2 list` shows four (definitions in `deploy/ecosystem.config.js`):

| PM2 name | What it runs | Bind/role |
|---|---|---|
| `api` | `venv/bin/gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 3 -b 127.0.0.1:8000` | HTTP API |
| `worker` | `venv/bin/celery -A app.workers.celery_app worker -Q default,crawl.http.0..3,crawl.render,qa,alerts,reports,sheets.sync,index.check,maintenance --concurrency=4` | background jobs |
| `beat` | `venv/bin/celery -A app.workers.celery_app beat -S redbeat.RedBeatScheduler` | scheduled jobs (due rechecks, partition roll, retention, weekly index sweep) |
| `frontend` | `npm start` (in `frontend/`) | Next.js :3000 |

> The PM2 processes set `cwd` to `backend/`/`frontend/` and use `interpreter:"none"`
> so Python can import `app.*` and load `.env`. If you ever see
> `ModuleNotFoundError: app.workers`, the cwd/venv path is wrong — fix the PM2 def,
> don't hack `PYTHONPATH`.

### Database & Redis
- **Postgres:** db **`linksentinel`** on the CloudPanel-managed Postgres 16.
  Access on the box: `sudo -u postgres psql -d linksentinel`. The app connects via
  the `DATABASE_URL` in `.env` (asyncpg DSN). `DB_USE_PGBOUNCER` controls
  prepared-statement behavior — on this single host it points at Postgres directly.
- **Redis:** local, used for the Celery broker (db 1), result backend (db 2), and
  RedBeat. `redis-cli ping` → `PONG`.

### How to deploy a change (the established workflow)
From the repo on this machine:
```bash
# 1) Frontend-only change:
tar czf - frontend/components frontend/lib | \
  ssh root@72.62.81.34 "tar xzf - -C /home/ls_user/htdocs/72.62.81.34.nip.io && \
  cd /home/ls_user/htdocs/72.62.81.34.nip.io/frontend && npm run build && pm2 restart frontend"

# 2) Backend code change (no schema):
tar czf - backend/app | \
  ssh root@72.62.81.34 "tar xzf - -C /home/ls_user/htdocs/72.62.81.34.nip.io && \
  pm2 restart api worker beat"

# 3) Backend schema change (new alembic migration):
tar czf - backend/app backend/alembic | \
  ssh root@72.62.81.34 "tar xzf - -C /home/ls_user/htdocs/72.62.81.34.nip.io && \
  cd /home/ls_user/htdocs/72.62.81.34.nip.io/backend && \
  venv/bin/alembic upgrade head && pm2 restart api worker beat"
```
Then verify: `curl -sk -o /dev/null -w '%{http_code}' https://72.62.81.34.nip.io/`
(expect `200`) and `pm2 list`. Always `git commit` what you deployed so the repo
matches the server.

> **A GitHub remote + `git pull` deploy is recommended** to end the tar juggling
> (then: `git pull && pip install -r requirements.txt && alembic upgrade head &&
> npm run build && pm2 restart all`). Not yet set up.

---

## 8. Auth & durable session (don't re-break this)

- **Tokens:** `POST /auth/login` → `{access_token, refresh_token}`. Access TTL 15
  min; refresh TTL 7 days (rotating — every refresh returns a new pair).
- **Frontend token manager (`frontend/lib/api.ts`):** stores both tokens in
  `localStorage`, attaches the access token to every request, and on a **401**
  transparently calls `POST /auth/refresh`, retries the request, and updates
  storage. `WorkspaceApp` also **proactively refreshes every 10 min**. Real logout
  only happens when the 7-day refresh token finally dies (fires an
  `ls-auth-expired` event → "Session expired"). This fixed the old "logged out
  after a few minutes / on tab close" bug — **keep the refresh-and-retry path
  intact** if you touch `api()`.

---

## 9. Environment variables

`backend/.env` (chmod 600, NOT in git) currently sets these keys (values are
secrets — read them on the server if needed, never print them in chat):

```
ENVIRONMENT, DEBUG, LOG_JSON
DATABASE_URL, DB_USE_PGBOUNCER
REDIS_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND
JWT_SECRET, SECRETS_ENCRYPTION_KEY                  ← regenerated on this deploy
STORAGE_BACKEND                                     ← "local" (blobs on disk under var/storage)
PROXY_ENABLED, PROXY_MODE, PROXY_VERIFY_TLS, PROXY_TIMEOUT
IPROYAL_PROXY_HOST/PORT/USERNAME/PASSWORD
RENDER_ENABLED                                      ← false (no Playwright pool installed)
SERP_PROVIDER=serper, SERPER_API_KEY
GOOGLE_CSE_API_KEY, GOOGLE_CSE_CX                   ← fallback provider (CSE)
GOOGLE_SHEETS_ENABLED, GOOGLE_SA_JSON_FILE, GOOGLE_MAIN_SHEET_ID,
GOOGLE_MAIN_PROJECT_COL, GOOGLE_MAIN_URL_COL
SITE_METRICS_ENABLED, SITE_METRICS_PROVIDER, SIMILARWEB_HOST/ENDPOINT, RAPIDAPI_KEY
```
Everything else falls back to the defaults in `app/core/config.py` — that file
documents each one. To add a setting: add a field there (never read `os.environ`
elsewhere). Booleans/CSV lists are parsed by validators in that file.

---

## 10. Security must-knows (carry these forward)

- **Secrets are env-only.** Never hardcode credentials; never commit `.env` or
  `service-account.json` (both are server-only). `.env` and the SA json are
  `chmod 600`.
- **Rotate exposed keys.** The IPRoyal password, RapidAPI key, serper key, and any
  Google keys were pasted in chat/screenshots during development → the user should
  rotate all of them. `JWT_SECRET` and the Fernet key were regenerated on the last
  deploy (so everyone re-logs-in once — expected).
- **SSRF guard:** target URLs are validated before any proxy fetch — **do not
  disable it.**
- **Refused capabilities (keep refusing):** CAPTCHA-solving / bot-protection
  evasion. This is a defensive QA tool, not an evasion tool.
- **Least privilege:** the Google SA should only be shared on the specific sheets
  it needs.
- **Prod DB writes are gated.** The harness's auto-mode classifier will (correctly)
  **block direct `UPDATE`/destructive SQL against the live DB** unless the user
  explicitly authorizes it. Prefer a code path / migration, or ask the user. Don't
  try to work around the block.

---

## 11. Current state & known gotchas

**Done & live (Phases 0–7):** proxy escalation, Sheets ingest + write-back, link
identity + duplicates + assignment history, index checking (serper), dynamic ERP
analytics, **versioned reports + non-technical Reports UI**, partition-drop
retention, `/healthz` `/readyz` `/metrics`. Migrations through `0006`. 87 unit
tests pass on the server. Real data present (backlinks imported; a real index sweep
ran: ~17 indexed / ~60 not-indexed).

**Recently shipped (most recent work):**
- Durable session / auto-refresh (§8).
- Company-vs-project dashboard scope switch (§5).
- Reports redesign: guided builder, project names, filter summaries, grouped
  version history (§5).
- Backend `ReportOut` now returns `project_name` (resolved; "All projects" when
  workspace-wide) and the `filters` used.

**Gotchas you will hit:**
- **Python 3.13 wheels:** pin `asyncpg>=0.30`, `lxml>=5.3`, `greenlet>=3.1`,
  `pydantic>=2.10` (older pins fail to compile on 3.13). Already fixed in
  `requirements.txt`.
- **PgBouncer / prepared statements:** if you ever route through PgBouncer in
  transaction mode, server-side prepared statements break — `DB_USE_PGBOUNCER`
  disables them. On this single host it's direct-to-Postgres.
- **Google smart-chip cells:** the main sheet's "Project Sheet URL" must be a
  **plain URL**, not a Google "smart chip" — the API can't read the chip's target.
- **Reports versioning historical data:** rows created *before* the version column
  existed were backfilled to `version=1, is_latest=true`, so several can look like
  duplicate "Latest v1". The **UI derives version numbers from recency** to mask
  this; a one-time SQL renumber (`ROW_NUMBER() OVER (PARTITION BY workspace_id,
  report_type, project_id ORDER BY created_at)`) would clean the stored data **but
  requires the user to authorize a prod DB write** (the classifier blocks it
  otherwise).
- **CRLF warnings on git add** (Windows) are harmless.
- **`backend/app.zip`** is a stale artifact — ignore it.

**Pending / TODO (offered, not done):**
1. **GitHub remote + one-command deploy** (replace tar-over-SSH).
2. **Scheduled report generation + email/Sheets delivery** (digest mode).
3. **Per-link-type QA rules** (e.g., treat directory nofollow as acceptable).
4. Optional **one-time report renumber** SQL (needs user authorization).
5. User should **rotate the exposed keys** (§10).

---

## 12. Runbook / common commands

```bash
# SSH in
ssh root@72.62.81.34

# Process health / logs
pm2 list
pm2 logs api --lines 50 --nostream
pm2 logs worker --lines 50 --nostream
pm2 restart api worker beat frontend     # or `pm2 restart all`

# Health checks
# NOTE: /healthz /readyz /metrics are at the BACKEND ROOT (not under /api/v1), and
# nginx only proxies /api/v1 — so reach them on the box against the backend port:
ssh root@72.62.81.34 "curl -s localhost:8000/healthz; curl -s localhost:8000/readyz"  # DB+Redis ready
# Public surface: frontend (expect 200) and any /api/v1 route (401 = up, auth-gated):
curl -sk -o /dev/null -w '%{http_code}\n' https://72.62.81.34.nip.io/                 # frontend
curl -sk -o /dev/null -w '%{http_code}\n' https://72.62.81.34.nip.io/api/v1/reports   # API (401 = up)

# Database (on the box)
sudo -u postgres psql -d linksentinel
#   e.g. SELECT count(*) FROM backlinks;  SELECT report_type, version, is_latest FROM reports;

# Migrations (on the box, in backend/)
cd /home/ls_user/htdocs/72.62.81.34.nip.io/backend
venv/bin/alembic current
venv/bin/alembic upgrade head
venv/bin/alembic revision -m "describe change"   # then edit the generated file

# Tests (on the box, in backend/)
venv/bin/pytest -q

# Redis
redis-cli ping
```

**Local dev (this machine):** the repo is at
`C:\Users\AR Computer\Desktop\backlinks qa`. Shell is PowerShell primary; a Bash
(Git Bash) tool is also available for POSIX scripts. Frontend `node_modules` may
not be installed locally — the **build is done on the server**, so a clean local
`npm run build` isn't part of the loop.

---

## 13. Where to go deeper

- **`CLAUDE.md`** — the short always-loaded working guide (rules, commands, conventions).
- **`backend/app/core/config.py`** — every behavior/tunable, heavily commented.
- **`docs/DEVELOPMENT-PLAN.md`** — the phased plan and rationale.
- **`docs/FINAL-STATUS.md`** — phase-by-phase status + recommendations.
- **`docs/01-product-requirements.md`** — product requirements.
- **`docs/02-system-architecture.md`** — system architecture detail.
- **`docs/03-production-runbook.md`** — production runbook.
- **`docs/FINAL-YEAR-PROJECT-REPORT.md`** — narrative project report.
- **`backend/app/services/*`** — business logic; start with `report_service.py`,
  `analytics_service.py`, `sheet_sync_service.py`, `index_service.py`.
- **`frontend/components/workspace-app.tsx`** — the whole UI in one tree; search for
  `ReportsDesk`, `AnalyticsDesk`, `Overview`, `Backlinks`, `SheetsDesk`.

*This system is a long-term, scalable production solution — keep changes fully
connected, relational, dynamic, and reliable. When in doubt, prefer a migration or
a code path over a one-off manual mutation, and never weaken the security posture
in §10.*
