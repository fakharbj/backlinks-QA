# LinkSentinel — Final Status & Recommendations

Live at **https://72.62.81.34.nip.io/**. All planned phases are deployed; 87 unit
tests pass on the server. This doc records what's done, what you still need to
supply, and the recommendations to keep it reliable long‑term.

## Delivered (Phases 0–7)

| Phase | What it does | State |
|---|---|---|
| 0 | Removed dead materialized‑view path + the wasteful 2‑min refresh job | ✅ live |
| 1 | IPRoyal Web Unblocker proxy (escalate‑on‑block, redirect‑unwrap, JS proxy‑render) | ✅ live |
| 2 | Google Sheets ingest (global main → project sheets, reuse import pipeline, throttled) | ✅ live |
| 3 | Link identity + duplicate detection (source+target‑domain) + assignment history | ✅ live |
| 4 | Index/non‑index checking framework (queue/dedup/UI/weekly) — **needs a SERP key** | ⚙️ needs CSE key |
| 5 | Dynamic ERP analytics (filters + connected facets + group‑by pivots) | ✅ live |
| 6 | Versioned reports (frozen snapshots) + dynamic report filters + Sheets write‑back | ✅ live |
| 7 | Hardening: partition‑drop retention (O(1) vs DELETE), `/healthz` + `/readyz` probes | ✅ live |

Migrations applied through `0006`. Worker consumes all queues incl. `sheets.sync`
and `index.check`. Beat runs due‑rechecks, partition roll, retention, and the
weekly index sweep.

## What you still need to supply (2 inputs)

1. **Google Custom Search key** → makes index checking reliable (Google scraping
   returns a JS‑only shell; the official API returns clean JSON, free 100/day).
   Create a Programmable Search Engine + Custom Search API key, then in `.env`:
   ```
   SERP_PROVIDER=google_cse
   GOOGLE_CSE_API_KEY=...
   GOOGLE_CSE_CX=...
   ```
2. **`service-account.json`** re‑upload to `backend/` → resumes Google Sheets
   sync + write‑back. For write‑back the SA needs **Editor** (not just Viewer) on
   the project sheets.

## Recommendations (reliability, security, scale)

**Deployment**
- Set up a **GitHub remote + `git pull` deploy** to end the file‑juggling. Today
  deploys are a tarball‑over‑SSH; a remote makes it `git pull && pip install -r
  requirements.txt && alembic upgrade head && npm run build && pm2 restart all`.
- `deploy/ecosystem.config.js` captures the PM2 processes (correct cwd + venv paths).

**Security**
- **Rotate every key shared in chat/screenshots**: IPRoyal password, RapidAPI key,
  and any Google keys. `.env` is `chmod 600`; `JWT_SECRET`/Fernet were regenerated
  on this deploy (so everyone re‑logs‑in once — expected).
- Keep the Google service account **least‑privilege** (share only the needed sheets).
- The SSRF guard validates target URLs before proxying — don't disable it.

**Reliability**
- Index checking: prefer **Google CSE** (official, free tier). If you outgrow
  100/day, the `serp` provider is pluggable — drop in a paid SERP API.
- Proxy is **escalate‑on‑block** (cheap): only blocked pages spend IPRoyal bandwidth.
  Switch `PROXY_MODE=always` only if specific sites still slip through.
- Monitoring: `GET /readyz` (DB+Redis) for uptime checks; `GET /metrics` for
  Prometheus; `pm2 status` for process health.

**Scale (your target: ~1–2M backlinks)**
- History tables (`crawl_results`, `backlink_history`) are month‑partitioned and now
  retention drops whole partitions. If `index_checks` grows large, partition it the
  same way (it's deduped by source URL, so it grows slowly).
- Analytics is whitelisted + indexed; add a dimension by editing one map in
  `analytics_service.py`.
- Postgres backups: schedule `pg_dump`/PITR (CloudPanel or cron) — the DB is the
  single source of truth for QA/results.

**Cost watch**
- IPRoyal (per‑request, escalate mode), Google CSE (free ≤100/day), RapidAPI
  Similarweb (per‑request). All gated by `*_ENABLED` flags.

## Possible next features (beyond the plan)
- Scheduled report generation + email/Sheets delivery (digest mode).
- Per‑link‑type QA rules (e.g., treat "directory" nofollow as acceptable).
- Read‑only public API tokens for clients.
- A render‑pool (Playwright) if many sources are pure SPAs (Crunchbase‑style).

---
*All code is committed; the server mirrors the repo. No secrets are stored in git.*
