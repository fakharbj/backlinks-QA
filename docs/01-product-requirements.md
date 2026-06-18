# LinkSentinel — Backlink QA & Monitoring Platform
## Step 1 — Product Requirements Document (PRD)

| Field | Value |
|---|---|
| **Product (working name)** | LinkSentinel |
| **Document** | Product Requirements Document |
| **Version** | 1.0 (Draft for build) |
| **Status** | Approved for implementation |
| **Date** | 2026-06-16 |
| **Owner** | Product / Engineering |
| **Audience** | Engineering, QA, SEO Ops, Stakeholders |
| **Deliverable** | Step 1 of 10 (PRD → Architecture → Schema → API → Backend → Crawler/QA Engine → Frontend → Docker → Tests → README/Deploy) |

---

## 1. Executive Summary

LinkSentinel is an enterprise-grade **Backlink Quality Assurance, monitoring, validation, reporting, and alerting platform** for SEO and link-building teams that manage thousands to millions of backlinks across many clients, campaigns, and vendors.

The product answers one core operational question for **every** backlink, continuously and at scale:

> "Is this backlink **live, correct, indexable, and passing the SEO value we paid for** — and if not, **exactly what is wrong, how severe is it, and what should we do about it**?"

It does this by crawling source pages (with JavaScript rendering when required), running a deterministic battery of ~150 technical-SEO QA checks, computing an explainable 0–100 risk score, classifying each link (PASS / WARNING / FAIL / UNKNOWN / NEEDS_MANUAL_REVIEW), detecting changes over time, alerting on regressions, and producing client/campaign/vendor reports.

Every check has a **code, category, severity, plain-English explanation, and a concrete recommendation** — so the output is defensible to clients and actionable by the team.

---

## 2. Problem Statement & Background

Link-building is expensive and fragile. After a backlink is placed, dozens of things silently go wrong over time:

- The publisher **removes the link** or edits the article.
- A `dofollow` link is **changed to `nofollow`**, `sponsored`, or `ugc`.
- The page is set to **`noindex`** or blocked by **robots.txt** / **X-Robots-Tag**.
- The page **404s, 410s, 5xxs**, or gets parked / soft-404'd.
- The page **canonicalizes to another URL/domain**, consolidating equity away.
- The **anchor text changes**, the **target URL changes**, or the target itself **redirects**.
- The link is present in raw HTML but **rendered away by JS**, hidden via CSS, buried in a comment, or stuffed in a footer with hundreds of outbound links.
- The page sits behind **Cloudflare / CAPTCHA / WAF**, so search engines (and naive crawlers) can't see the link.

Teams today verify links with **manual spot-checks, spreadsheets, and ad-hoc scripts**. This does not scale, is error-prone, misses subtle technical-SEO issues (X-Robots, canonical chains, soft-404s, JS-only links), and produces no audit trail or client-ready evidence.

**LinkSentinel replaces the spreadsheet** with a system of record: import once, verify continuously, score consistently, alert automatically, and report on demand.

---

## 3. Goals, Objectives & Success Metrics

### 3.1 Business goals
- Reduce time-to-detect a lost/degraded backlink from **weeks to <24h**.
- Cut manual QA effort per 1,000 links by **>80%**.
- Provide **client-ready, defensible** QA evidence (improves retention & upsell).
- Enable **vendor accountability** (failure rates per vendor/campaign).

### 3.2 Product goals
- Verify **100% of imported backlinks** on a schedule, not a sample.
- Make **every verdict explainable** (issue → severity → reason → recommendation).
- Scale linearly to **1M+ backlinks** with polite, compliant crawling.
- Catch **technical-SEO-grade** issues, not just "is the link there."

### 3.3 Success metrics (KPIs)
| Metric | Target |
|---|---|
| Backlink check accuracy (vs. manual audit) | ≥ 98% |
| False-positive "link missing" rate | ≤ 1% |
| Mean time to detect regression | < 24h (daily schedule) |
| Crawl success rate (non-bot-blocked domains) | ≥ 97% |
| P95 dashboard load | < 2s |
| Sustained crawl throughput @ 1M scale | ≥ 200 pages/sec aggregate |
| Scheduled-run completion SLA | 100% of due links checked within window |

### 3.4 Non-goals (explicitly out of scope)
- We are **not** a backlink **discovery / index** tool (we don't replace Ahrefs/Semrush' link graphs). We **verify** links you already know about; we *integrate* with those tools for import.
- We do **not** perform outreach, email the publisher, or auto-negotiate fixes (we generate the recommendation/ticket; sending is future/optional).
- We are **not** a rank tracker or keyword research tool.
- We do **not** guarantee Google's actual indexing decision — we estimate **indexability** and optionally verify via GSC/`site:`; the ground truth is labeled "Indexed / Not Indexed / Unknown / Cannot Verify".
- We do **not** bypass bot protection, solve CAPTCHAs, or evade WAFs. We **detect** them and flag for manual review (ethical crawling, see §9.6).

---

## 4. Target Users & Personas

**Context:** SEO agencies, in-house enterprise SEO teams, and link-building vendors managing many clients/projects.

| Persona | Description | Primary needs |
|---|---|---|
| **Admin** | Agency owner / Ops lead. Owns the workspace, billing, users, integrations. | Manage team & roles, configure integrations/alerts, audit logs, all data. |
| **Manager** | Account/Campaign manager. Owns projects & vendor relationships. | Create projects, assign QA, set schedules/alerts, vendor & campaign reports. |
| **QA Specialist** | Runs the day-to-day verification. | Import links, run/recheck crawls, triage issues, manual overrides, notes. |
| **Viewer** | Internal stakeholder or **external client** (scoped). | Read-only dashboards, tables, and exports for their project(s) only. |

> **Multi-tenancy model:** `Workspace` (tenant) → `Projects` → `Backlinks`. Every row is scoped by `workspace_id` (and `project_id`). Viewers/clients can be restricted to specific projects.

---

## 5. RBAC / Permissions Matrix

| Capability | Admin | Manager | QA Specialist | Viewer |
|---|:--:|:--:|:--:|:--:|
| Manage workspace, billing, integrations | ✅ | — | — | — |
| Manage users & roles | ✅ | — | — | — |
| View audit logs | ✅ | (own projects) | — | — |
| Create / edit / delete projects | ✅ | ✅ | — | — |
| Assign members to projects | ✅ | ✅ | — | — |
| Manage vendors & campaigns | ✅ | ✅ | ✅ | — |
| Import backlinks | ✅ | ✅ | ✅ | — |
| Edit backlink records | ✅ | ✅ | ✅ | — |
| Run / recheck crawls | ✅ | ✅ | ✅ | — |
| Manual override of a verdict | ✅ | ✅ | ✅ | — |
| Configure schedules & alerts | ✅ | ✅ | (suggest only) | — |
| View dashboards / tables / details | ✅ | ✅ | ✅ | ✅ (scoped) |
| Export reports (CSV/XLSX/PDF) | ✅ | ✅ | ✅ | ✅ (scoped) |
| Delete data / projects | ✅ | ✅ (own) | — | — |

Enforcement: server-side on every endpoint via `workspace_id` + role checks; project-level membership further narrows Manager/QA/Viewer. All mutations write `audit_logs`.

---

## 6. User Stories / Jobs To Be Done (representative)

- **As a QA Specialist**, I import 5,000 backlinks from a vendor's XLSX, and the system normalizes URLs, dedupes, and queues them for verification so I don't hand-check anything.
- **As a QA Specialist**, I open a failed link and immediately see *why* (e.g., "PAGE_NOINDEX via X-Robots-Tag header"), the raw header, the extracted link HTML, and the recommended action.
- **As a Manager**, I get a Slack alert the moment a `dofollow` link we paid for flips to `nofollow`, with the link, vendor, campaign, and score delta.
- **As a Manager**, I export a branded monthly PDF for "Acme Co" showing live %, lost links, and per-campaign health.
- **As an Admin**, I see vendor failure rates ranked, so I can renegotiate or drop the worst publisher.
- **As a Viewer (client)**, I log in and see only my project's dashboard and can download the current report — nothing else.
- **As a QA Specialist**, when a page is behind Cloudflare/CAPTCHA, the link is marked `NEEDS_MANUAL_REVIEW` (not silently failed), and I confirm manually with an override + note.

---

## 7. Tech Stack — Validation & Recommendation

**Verdict: the proposed stack is appropriate and we will use it.** It maps cleanly to the workload (async I/O-bound crawling, relational QA data, heavy data grids). Endorsements + senior refinements:

| Layer | Proposed | Decision / Refinement |
|---|---|---|
| Frontend | Next.js + React + TS + Tailwind | ✅ Use **App Router**, **TanStack Query** (server state), **TanStack Table** (1M-row virtualized grid), **shadcn/ui** components. |
| Backend | FastAPI (Python) | ✅ Pair with **Pydantic v2** + **SQLAlchemy 2.0 (async)** + **Alembic** migrations. |
| DB | PostgreSQL | ✅ System of record. Add **table partitioning** for `crawl_results`/`backlink_history` at scale; **materialized views** for dashboard aggregates. |
| Queue | Celery + Redis | ✅ as requested. **Refinement:** the crawler is async (httpx/aiohttp); Celery is sync-first. We run **two worker pools** — a lightweight pool that drives an internal async crawl batch, and a separate **Playwright pool** (heavy). For very high throughput, **`arq`** (async-native) is offered as a drop-in alternative in Step 2; default remains Celery per your spec. |
| Crawler | httpx/aiohttp + Playwright | ✅ **Tiered crawl**: cheap async HTTP first; **escalate to Playwright only when** the link is absent in raw HTML *and* the page looks JS-driven (cost control). |
| Parsing | BeautifulSoup/lxml | ✅ `lxml` parser for speed; `selectolax` optional fast path at scale. |
| Raw HTML storage | (Postgres implied) | **Refinement:** store large raw HTML/snapshots in **object storage (S3/MinIO)**, keep only metadata + pointer in Postgres (keeps DB lean at 1M scale). |
| Rate limiting | (not specified) | **Add:** Redis **per-domain token buckets** + global concurrency caps. |
| Auth | JWT | ✅ short-lived access + refresh tokens; **Argon2** password hashing; reset-token table ready. |
| Deploy | Docker + Compose | ✅ Compose for dev/single-node; **K8s manifests** offered as enterprise upgrade in roadmap. |

(Full rationale, diagrams, and the async-worker design are deferred to **Step 2 — System Architecture**.)

---

## 8. Functional Requirements

### 8.1 Authentication & Workspaces
- Email/password **login**, **register**, **logout**; **password-reset-ready** (token table + endpoints stubbed).
- **JWT** access (15 min) + refresh (7 day) tokens; refresh rotation.
- **Roles:** Admin, Manager, QA Specialist, Viewer (see §5).
- **Workspaces (tenants)** with member invitations; **project-level** membership for scoping.
- **Client/project separation** enforced at the data layer (`workspace_id`, `project_id` on every record).
- Account lockout after N failed logins; audit every auth event.

### 8.2 Project Management
Each project: `name`, `client_name`, `target_domain`, `target_urls[]`, `campaign`, `assigned_members[]`, `notes`, `tags[]`, `status` (Active/Paused/Archived), `created_at`, `last_checked_at`, default crawl/schedule settings, default "treat sponsored/ugc as follow?" policy.

### 8.3 Backlink Import
Support: **CSV**, **XLSX**, **manual single entry**, **bulk paste** (one URL/line or `source,target` pairs), **Google-Sheets-ready** (column mapping schema), **API import-ready** (documented endpoint), and **future Ahrefs/Semrush/Majestic** connectors (mapping layer defined now).

Pipeline requirements:
- **Column mapping UI** (map arbitrary headers → canonical fields).
- **Validation** with per-row error report (downloadable).
- **URL normalization** on ingest (§8.4) + **dedup** within project (by normalized `source_url`+`target_url`).
- **Resumable / partial-save**: large imports stream to a staging table; failures don't lose progress; an import has status `pending/processing/partial/completed/failed` with a row-level error log.
- Auto-create referenced **vendors/campaigns** if missing (with confirmation).

**Backlink record fields:** `source_page_url`, `target_url`, `expected_target_url`, `expected_anchor_text`, `expected_rel` (e.g., `dofollow`), `campaign`, `vendor`, `client`, `cost` (optional), `placement_date`, `expected_status` (e.g., live), `notes`, `tags[]`, plus system fields (status, score, last/next check, issues).

**Sample CSV format** (see §12).

### 8.4 URL Normalization (canonicalization rules)
A single, well-tested normalizer used on **ingest, comparison, and crawl** (test-covered in Step 9). Rules:
1. Trim whitespace; **percent-decode** then safely re-encode; lowercase the **scheme** and **host**.
2. **Scheme:** record as-is; comparison treats `http`↔`https` as "same resource, protocol differs" (flag downgrade separately).
3. **Host:** lowercase; **IDN/punycode** normalize (`xn--…` ↔ unicode); strip default ports (`:80`/`:443`).
4. **www vs non-www:** treated as the **same registrable host** for *matching* purposes, but the discrepancy is recorded (so we can flag a missing www→non-www redirect).
5. **Path:** preserve case (paths are case-sensitive); collapse duplicate slashes; resolve `.`/`..`; **trailing slash** handled per policy (configurable: strict vs. lenient — default lenient: `/a` ≡ `/a/`).
6. **Query:** sort params; drop known tracking params (`utm_*`, `gclid`, `fbclid`, `mc_eid`, …) for comparison (configurable allow/deny list); preserve original for crawling.
7. **Fragment (`#…`):** removed for comparison (except SPA hashbang `#!` retained behind a flag).
8. **Relative URLs:** resolved against the page's base/`<base href>` and final (post-redirect) URL.
9. Output both a **normalized form** (for matching/indexing) and the **original** (for crawling/auditing).

Two URLs are a **target match** if their normalized forms are equal under the active policy; otherwise we attempt a **redirect-aware match** (target may redirect to the expected target — acceptable, but flagged).

### 8.5 Crawling Engine (requirements)
- Crawl source pages with **configurable per-domain crawl-delay**, **retries** (exponential backoff + jitter), **timeouts** (connect/read), and **max redirects**.
- **User-agent**: configurable; rotation pool; honest default identifying the bot + contact (compliant). Optional Googlebot-UA mode for indexability parity (clearly logged).
- **Proxy support** (config-ready; off by default).
- **Detect & classify**: bot protection, **CAPTCHA** pages, **Cloudflare/JS browser challenge**, **soft-404**, **empty page**, **thin placeholder/parked** page, **server errors**, **redirect loops**, **excessive redirects**.
- Store raw response **metadata** (status, headers, content-type, size, encoding), **crawl timestamp**, **crawl duration**, **final URL after redirects**, and a **raw HTML pointer** (object storage).
- **Tiered rendering:** raw HTTP fetch first; escalate to **Playwright** only when needed (link not in raw HTML + JS-likely). Record which mode found the link (`raw` vs `rendered`).
- **Politeness/safety:** robots.txt awareness (§8.6.J), global + per-domain concurrency caps, never hammer a host.

### 8.6 QA Check Catalog (the core)
Every check below carries: **Code · Category · Severity · Default Issue Label · Recommendation**. Severities: `CRITICAL` (hard-fail), `HIGH`, `MEDIUM`, `LOW`, `INFO`. (Scoring impact in §8.8; full enum in §8.9.)

#### A. Network / Transport (`NET-*`)
| Code | Check | Severity | Label | Recommendation |
|---|---|---|---|---|
| NET-01 | DNS resolution failure | CRITICAL | DNS_ERROR | Domain may be expired/parked. Confirm domain status; link is effectively lost. |
| NET-02 | Connection timeout (after retries) | HIGH→UNKNOWN | TIMEOUT | Host slow/unreachable; recheck later. If persistent, treat as down. |
| NET-03 | SSL/TLS handshake error | CRITICAL | SSL_ERROR | Cert/TLS broken; users & crawlers can't reach page. Ask publisher to fix HTTPS. |
| NET-04 | Invalid/expired/mismatched certificate | HIGH | SSL_ERROR | Cert invalid; flag to publisher; equity at risk. |
| NET-05 | Connection reset / refused | HIGH→UNKNOWN | HTTP_ERROR | Possible firewall/WAF; recheck and verify manually. |
| NET-06 | Unknown network error | MEDIUM→UNKNOWN | HTTP_ERROR | Transient; auto-retry on schedule. |

#### B. HTTP Status (`HTTP-*`)
| Code | Status | Severity | Label | Recommendation |
|---|---|---|---|---|
| HTTP-200 | 200 OK | INFO | LINK_FOUND-context | Page reachable; continue checks. |
| HTTP-301 | 301 permanent redirect | LOW/MEDIUM | REDIRECT_CHAIN | Permanent move; verify final destination still hosts the link. |
| HTTP-302 | 302 temporary redirect | MEDIUM | REDIRECT_CHAIN | Temporary redirect on a backlink page is risky; ask publisher to serve 200 or 301 to a stable URL. |
| HTTP-307/308 | 307/308 redirect | LOW/MEDIUM | REDIRECT_CHAIN | Follow chain; confirm link survives at destination. |
| HTTP-400 | 400 Bad Request | HIGH | HTTP_ERROR | Page broken/malformed request; verify URL correctness. |
| HTTP-401 | 401 Unauthorized | HIGH | HTTP_ERROR | Login-gated; not publicly indexable — request public placement. |
| HTTP-403 | 403 Forbidden | HIGH | SOURCE_403 | Access blocked (often WAF/bot rules); verify manually; may still be live for users. |
| HTTP-404 | 404 Not Found | CRITICAL | SOURCE_404 | Backlink lost unless page restored. Ask publisher to restore URL or 301 to equivalent. |
| HTTP-410 | 410 Gone | CRITICAL | SOURCE_404 | Page permanently removed; backlink lost. Seek replacement placement. |
| HTTP-429 | 429 Too Many Requests | MEDIUM→UNKNOWN | HTTP_ERROR | We were rate-limited; back off & recheck (not necessarily a publisher fault). |
| HTTP-500 | 500 Internal Server Error | CRITICAL | SOURCE_5XX | Server error; recheck; if persistent, link is effectively down. |
| HTTP-502 | 502 Bad Gateway | CRITICAL | SOURCE_5XX | Upstream failure; recheck; escalate if persistent. |
| HTTP-503 | 503 Service Unavailable | HIGH→UNKNOWN | SOURCE_5XX | Often transient/maintenance; recheck on schedule. |
| HTTP-504 | 504 Gateway Timeout | HIGH→UNKNOWN | SOURCE_5XX | Upstream timeout; recheck later. |
| HTTP-4XX/5XX-other | Any other 4xx/5xx | HIGH | HTTP_ERROR | Inspect status; verify availability. |

#### C. Redirect QA (`RDR-*`)
| Code | Check | Severity | Label | Recommendation |
|---|---|---|---|---|
| RDR-01 | Full redirect chain captured (each hop: URL, status) | INFO | — | Evidence stored. |
| RDR-02 | Redirect count > threshold (default >3) | MEDIUM | REDIRECT_CHAIN | Reduce hops; long chains dilute/ slow crawling. |
| RDR-03 | Redirect **loop** | CRITICAL | REDIRECT_LOOP | Page unreachable; ask publisher to fix loop. |
| RDR-04 | HTTP→HTTPS upgrade | INFO/LOW | — | Healthy; note only. |
| RDR-05 | HTTPS→HTTP **downgrade** | HIGH | REDIRECT_CHAIN | Insecure downgrade; flag to publisher. |
| RDR-06 | www/non-www redirect present/absent | LOW | — | Note canonicalization behavior. |
| RDR-07 | Cross-domain redirect of **source** page | HIGH | REDIRECT_CHAIN | Source moved to another domain; verify link still present there. |
| RDR-08 | Backlink still present **after** following redirects | (drives LNK) | — | Re-run link presence on final URL. |
| RDR-09 | **Target URL** itself redirects | MEDIUM | — | Acceptable if final == expected target; otherwise WRONG_TARGET. |
| RDR-10 | Final target ≠ expected target | HIGH | WRONG_TARGET | Link points somewhere other than agreed; request correction. |
| RDR-11 | Temporary (302/307) on critical hop | MEDIUM | REDIRECT_CHAIN | Prefer permanent redirects for stable equity. |

#### D. Link Presence QA (`LNK-*`)
| Code | Check | Severity | Label | Recommendation |
|---|---|---|---|---|
| LNK-01 | Backlink present (normalized match) on final source page | INFO/PASS | LINK_FOUND | OK. |
| LNK-02 | Backlink **missing** | CRITICAL | LINK_MISSING | Ask publisher to restore the agreed link. |
| LNK-03 | Exact target match | INFO | — | OK. |
| LNK-04 | Normalized match only (e.g., trailing slash/scheme) | LOW | — | Acceptable; note minor mismatch. |
| LNK-05 | Target redirects but resolves to expected target | LOW | — | Acceptable; prefer direct link to final URL. |
| LNK-06 | Link points to **wrong page** (same domain) | HIGH | WRONG_TARGET | Request correction to agreed target URL. |
| LNK-07 | Link points to **wrong domain** | CRITICAL | WRONG_TARGET | Not our link/target; investigate. |
| LNK-08 | Multiple links to same target | INFO | — | Note count; not an error. |
| LNK-09 | Link only in **rendered** DOM (JS) | MEDIUM | JS_RENDER_REQUIRED | Search engines may under-credit JS-only links; request server-rendered link. |
| LNK-10 | Link only in **raw** HTML (not rendered) | MEDIUM | LINK_HIDDEN | JS removes it at runtime; verify it's truly visible. |
| LNK-11 | Link hidden in **HTML comment** | HIGH | LINK_HIDDEN | Not a real link; request live placement. |
| LNK-12 | Link hidden via **CSS** (display:none/visibility/0-size/off-screen) | HIGH | LINK_HIDDEN | Hidden links pass little/no value & risk spam; request visible placement. |
| LNK-13 | Link inside **`<noscript>`** | MEDIUM | LINK_HIDDEN | Only shown without JS; verify real visibility. |
| LNK-14 | Link inside **iframe** | HIGH | LINK_HIDDEN | Iframed links generally don't credit the parent; request inline link. |
| LNK-15 | Link inside sponsored/ad block | MEDIUM | LINK_SPONSORED | Likely ad unit; confirm it's editorial if editorial was agreed. |
| LNK-16 | Link inside UGC/comment section | MEDIUM | LINK_UGC | Comment links are low value & often `ugc`; confirm placement type. |
| LNK-17 | Link region: header/nav/sidebar/footer/body | LOW (footer/sidebar) / INFO (body) | — | Footer/sidebar site-wide links carry less editorial value; prefer in-content. |
| LNK-18 | Above/below the fold (best-effort, rendered) | INFO/LOW | — | In-content, above-fold preferred; informational. |
| LNK-19 | Surrounding text/context captured | INFO | — | Stored for relevance review. |

#### E. Anchor Text QA (`ANC-*`)
| Code | Check | Severity | Label | Recommendation |
|---|---|---|---|---|
| ANC-01 | Actual anchor captured | INFO | — | Stored. |
| ANC-02 | Exact match vs expected | INFO/PASS | — | OK. |
| ANC-03 | Partial match | LOW | — | Minor; confirm acceptable. |
| ANC-04 | Mismatch / changed since last crawl | MEDIUM | ANCHOR_CHANGED | Publisher edited anchor; request original anchor if contractual. |
| ANC-05 | Empty anchor | MEDIUM | ANCHOR_CHANGED | Anchor empty; request meaningful anchor. |
| ANC-06 | Image-only anchor | LOW | — | Uses image; capture `alt` as effective anchor. |
| ANC-07 | Image `alt` used as anchor signal | INFO | — | Recorded. |
| ANC-08 | Over-optimized exact-match money anchor | LOW/MEDIUM (warn) | — | Over-optimization risk; diversify anchors. |
| ANC-09 | Branded vs non-branded classification | INFO | — | Stored for anchor-profile analytics. |
| ANC-10 | Money-keyword classification flag | INFO | — | Stored; feeds anchor-profile risk. |

#### F. Rel Attribute QA (`REL-*`)
| Code | Check | Severity | Label | Recommendation |
|---|---|---|---|---|
| REL-01 | `dofollow` (no nofollow/sponsored/ugc) | INFO/PASS | — | OK (if follow expected). |
| REL-02 | `nofollow` when **follow expected** | HIGH | LINK_NOFOLLOW | Ask publisher to remove `rel=nofollow` per agreement. |
| REL-03 | `sponsored` | MEDIUM (policy) | LINK_SPONSORED | Expected for paid; if editorial was agreed, request change. |
| REL-04 | `ugc` | MEDIUM (policy) | LINK_UGC | Comment/UGC link; confirm placement type. |
| REL-05 | `noopener`/`noreferrer` present | INFO | — | No SEO impact; recorded. |
| REL-06 | Multiple rel values parsed | INFO | — | All values captured. |
| REL-07 | Rel changed since last crawl | HIGH | LINK_NOFOLLOW/CHANGED | Equity status changed; investigate & escalate. |

> **Policy hook:** the project setting *"treat sponsored/ugc as followable?"* controls whether REL-03/04 are HIGH (treated like nofollow) or just INFO. Default: paid campaigns expect `sponsored` (INFO); editorial campaigns treat it as HIGH.

#### G. Meta Robots QA (`MR-*`)
Parse `<meta name="robots">` **and** UA-specific `<meta name="googlebot|bingbot">`. Detect: `index/noindex`, `follow/nofollow`, `none`, `noarchive`, `nosnippet`, `max-snippet`, `max-image-preview`, `max-video-preview`, `unavailable_after`, conflicting/multiple tags.

| Code | Check | Severity | Label | Recommendation |
|---|---|---|---|---|
| MR-01 | `noindex` (page) | CRITICAL (if index expected) | PAGE_NOINDEX | Page won't be indexed; long-term noindex ≈ no link value. Request indexable placement. |
| MR-02 | `nofollow` (page-level) | HIGH | PAGE_NOFOLLOW | Page tells crawlers not to follow **any** links → no equity. Request removal. |
| MR-03 | `none` (= noindex,nofollow) | CRITICAL | PAGE_NOINDEX | Worst case; request indexable, followable placement. |
| MR-04 | `googlebot`-specific directive | HIGH/CRITICAL | PAGE_NOINDEX/NOFOLLOW | Googlebot-specific noindex/nofollow overrides generic; same recommendations. |
| MR-05 | Conflicting / multiple robots tags | MEDIUM | — | Ambiguous; Google takes most restrictive. Ask publisher to clean up. |
| MR-06 | `noarchive`/`nosnippet`/`max-*` | LOW/INFO | — | Display directives; minor; recorded. |
| MR-07 | `unavailable_after` in the past | HIGH | PAGE_NOINDEX | Scheduled de-index has passed; treat as noindex. |

#### H. X-Robots-Tag Header QA (`XR-*`)
Parse `X-Robots-Tag` response header(s), including UA-prefixed (`googlebot: noindex`). Same directive vocabulary as meta robots; **headers and meta combine — most restrictive wins.**

| Code | Check | Severity | Label | Recommendation |
|---|---|---|---|---|
| XR-01 | `noindex` via header | CRITICAL (if index expected) | X_ROBOTS_NOINDEX | Header-level noindex; page won't index. Request removal. |
| XR-02 | `nofollow` via header | HIGH | X_ROBOTS_NOFOLLOW | Header tells crawlers not to follow links → no equity. Request removal. |
| XR-03 | `none` via header | CRITICAL | X_ROBOTS_NOINDEX | noindex+nofollow at header level. Escalate. |
| XR-04 | Googlebot-specific X-Robots-Tag | HIGH/CRITICAL | X_ROBOTS_* | UA-targeted directive; same recommendations. |
| XR-05 | Conflicting/multiple header values | MEDIUM | — | Most restrictive applies; ask publisher to fix. |
| XR-06 | `unavailable_after` (header) passed | HIGH | X_ROBOTS_NOINDEX | Treat as noindex. |

#### I. Canonical QA (`CAN-*`)
| Code | Check | Severity | Label | Recommendation |
|---|---|---|---|---|
| CAN-01 | Canonical present & self-referential | INFO/PASS | — | Healthy. |
| CAN-02 | Canonical **missing** | LOW | — | Not fatal; Google infers. Note only. |
| CAN-03 | Canonical → another URL (same domain) | HIGH | CANONICAL_MISMATCH | Equity consolidates to canonical; ensure the **canonical** page also hosts/credits the link. |
| CAN-04 | Canonical → another **domain** | CRITICAL | CANONICAL_CROSS_DOMAIN | Equity leaves this domain entirely; link value largely lost. Escalate. |
| CAN-05 | Canonical → non-200 page | HIGH | CANONICAL_MISMATCH | Canonical target broken; signals confusion; flag to publisher. |
| CAN-06 | Canonical target redirects | MEDIUM | CANONICAL_MISMATCH | Canonical chain; verify final canonical. |
| CAN-07 | Canonical blocked by robots.txt | HIGH | CANONICAL_MISMATCH | Canonical uncrawlable; conflicting signals. |
| CAN-08 | Canonical target is noindex | HIGH | CANONICAL_MISMATCH | Consolidating to a noindex page ≈ value lost. |
| CAN-09 | Multiple canonical tags | MEDIUM | — | Ambiguous; Google may ignore. Ask publisher to keep one. |
| CAN-10 | Invalid/relative canonical URL | MEDIUM | CANONICAL_MISMATCH | Malformed canonical; resolve & flag. |
| CAN-11 | Canonical mismatch with source (the URL we crawled) | MEDIUM | CANONICAL_MISMATCH | Our recorded source isn't the canonical; reconcile records. |

#### J. Robots.txt QA (`RBT-*`)
| Code | Check | Severity | Label | Recommendation |
|---|---|---|---|---|
| RBT-01 | robots.txt exists & parsed | INFO | — | Stored. |
| RBT-02 | robots.txt unreachable / parse error | LOW | — | Treat as "allow all" per spec; note uncertainty. |
| RBT-03 | **Source page** disallowed (for Googlebot) | CRITICAL | ROBOTS_BLOCKED | Crawlers can't read the page/link → no value. Request unblock. |
| RBT-04 | **Target URL** disallowed | MEDIUM | ROBOTS_BLOCKED | Target uncrawlable; informational for our own site. |
| RBT-05 | **Canonical URL** disallowed | HIGH | ROBOTS_BLOCKED | See CAN-07. |
| RBT-06 | Googlebot-specific allow/disallow honored | INFO | — | UA-specific rules applied. |
| RBT-07 | Wildcards / `$` rules parsed | INFO | — | Correct matching. |
| RBT-08 | `crawl-delay` declared | INFO | — | Respect during crawl. |
| RBT-09 | Sitemap declarations captured | INFO | — | Stored. |

#### K. Indexability QA (`IDX-*`) — composite (see §8.7)
| Code | Check | Severity | Label | Recommendation |
|---|---|---|---|---|
| IDX-01 | Page likely **indexable** (all conditions pass) | INFO/PASS | — | Healthy backlink host. |
| IDX-02 | Page **not indexable** (any blocker) | inherits blocker | (blocker label) | Address the specific blocker (noindex/robots/etc.). |
| IDX-03 | Indexability **unknown** (CAPTCHA/WAF/JS inconclusive) | — | INDEXABILITY_UNKNOWN | Manual verification required. |
| IDX-04 | Optional external verification (GSC/`site:`/3rd-party) | INFO | — | Status: Indexed / Not Indexed / Unknown / Cannot Verify. |

#### L. Content-Type QA (`CT-*`)
| Code | Check | Severity | Label | Recommendation |
|---|---|---|---|---|
| CT-01 | `text/html` | INFO | — | Standard; run full checks. |
| CT-02 | PDF | MEDIUM | — | Mark **special backlink type**; HTML link checks N/A. (Future: scan PDF text for target URL.) |
| CT-03 | Image / plain text / JS / JSON / XML | MEDIUM | — | Non-HTML host; link-in-HTML checks not applicable; flag for review. |
| CT-04 | Downloadable file (attachment) | MEDIUM | — | Not a web page; review placement. |
| CT-05 | Unsupported / unknown content type | MEDIUM | — | Flag for manual review. |

#### M. Page Quality Signals (`PQ-*`) — optional/secondary
Capture (no hard fail unless noted): `title`, `meta description`, `H1`, **word count**, **language**, outbound/internal/external link counts, **page size**, **load time**.

| Code | Check | Severity | Label | Recommendation |
|---|---|---|---|---|
| PQ-01 | Title missing/empty | LOW | — | Quality signal; note. |
| PQ-02 | Duplicate title (across project) | LOW | — | Possible templated/thin site. |
| PQ-03 | Thin content (word count < threshold) | LOW/MEDIUM | — | Thin host pages carry less value. |
| PQ-04 | Excessive outbound links (> threshold) | MEDIUM | TOO_MANY_OUTBOUND_LINKS | Link-farm signal; equity diluted; review host quality. |
| PQ-05 | Slow load / large page | LOW | — | Performance note. |
| PQ-06 | Adult/gambling/pharma/spam keyword flags | MEDIUM (warn) | — | Risky neighborhood; review host suitability. |
| PQ-07 | Malware/suspicious flag (placeholder) | HIGH (warn) | — | Investigate host safety. |

#### N. Bot Protection / Access (`BOT-*`)
| Code | Check | Severity | Label | Recommendation |
|---|---|---|---|---|
| BOT-01 | CAPTCHA page detected | — | CAPTCHA_DETECTED | We don't solve CAPTCHAs; **manual review** required. |
| BOT-02 | Cloudflare / JS browser challenge | — | CAPTCHA_DETECTED | Try rendered fetch; if still blocked, manual review. |
| BOT-03 | WAF/firewall block (e.g., 403 w/ vendor signature) | — | SOURCE_403 | Verify manually; page may be live for real users. |
| BOT-04 | Soft-404 (200 but "not found"/parked content) | HIGH | SOFT_404 | Page effectively dead; treat as lost; seek replacement. |
| BOT-05 | Empty / blank page | HIGH | SOFT_404 | No content/link; flag. |
| BOT-06 | Thin placeholder / parked domain | HIGH | SOFT_404 | Domain likely expired/parked; link lost. |

#### O. Change Detection (`CHG-*`) — see §8.10
Diff current vs previous result; emit history events + (optionally) alerts.

### 8.7 Indexability & "Followability" composite logic (SEO-correct)
This is the platform's most important reasoning. We compute two booleans + evidence.

**A link passes SEO value (`is_followable_link == true`) only if ALL hold:**
1. The **link element** is not `rel=nofollow` (and, per project policy, not `sponsored`/`ugc`).
2. The **page** has no page-level `nofollow` — neither `<meta robots nofollow>` (MR-02/03/04) **nor** `X-Robots-Tag: nofollow` (XR-02/03/04). *(Page-level nofollow kills following of every link.)*
3. The **source page is crawlable** — not disallowed in robots.txt for Googlebot (RBT-03). *(If uncrawlable, the link can't even be discovered.)*
4. The link is **discoverable** in the HTML or rendered DOM that crawlers process (LNK-01), and not hidden (CSS/comment/iframe → reduces/zeros value).

**A source page is likely indexable (`is_indexable == true`) only if ALL hold:** HTTP 200 (after redirects); not robots.txt-blocked; not `meta noindex`; not `X-Robots noindex`; canonical is self or acceptable (not cross-domain/noindex); not soft-404/empty/thin; not login-gated (401); not redirected to an irrelevant URL; not CAPTCHA/WAF-blocked; content-type is HTML.

**Nuance captured & explained to users:** a `noindex,follow` page can still *follow* links short-term, but Google treats **long-term noindexed pages as effectively `noindex,nofollow`**, so we flag noindex source pages as a degraded SEO host (CRITICAL when index was expected). When any blocker is **unknowable** (CAPTCHA/WAF/JS-inconclusive), `is_indexable`/`is_followable` = **UNKNOWN**, not false → status becomes `NEEDS_MANUAL_REVIEW` rather than a false `FAIL`.

Optional external verification (`IDX-04`): Google Search Console URL Inspection API (when connected), a manual `site:`-search helper field, or a third-party API → records `Indexed / Not Indexed / Unknown / Cannot Verify` separately from our computed `is_indexable`.

### 8.8 Backlink Risk Scoring (0–100, deterministic & explainable)
**Algorithm:**
```
score = 100
score -= Σ deduction(issue)        # weighted by severity
score  = clamp(score, 0, 100)
for issue in detected:             # hard caps
    score = min(score, cap(issue)) # CRITICAL issues cap the ceiling
```
**Severity weights:**

| Severity | Deduction | Hard cap | Meaning |
|---|---|---|---|
| CRITICAL | −60 | **≤ 25** | Backlink is effectively broken/worthless. |
| HIGH | −25 | — | Major value loss (e.g., nofollow when follow expected). |
| MEDIUM | −10 | — | Notable warning. |
| LOW | −3 | — | Minor note. |
| INFO | 0 | — | Evidence only. |

**Grade bands (label):** `100 = Perfect` · `80–99 = Good` · `60–79 = Warning` · `30–59 = Risky` · `0–29 = Failed`.

**Hard-fail (CRITICAL) conditions** (cap ≤25 ⇒ band Failed/Risky): source not accessible (4xx/5xx/DNS/SSL), `LINK_MISSING`, `PAGE_NOINDEX`/`X_ROBOTS_NOINDEX` (when index expected), `ROBOTS_BLOCKED` (source), `CANONICAL_CROSS_DOMAIN`, `SOURCE_404/410`, `WRONG_TARGET` (wrong domain), `CAPTCHA_DETECTED`→review, `SOFT_404`, `REDIRECT_LOOP`.

**Minor (LOW/MEDIUM) conditions:** anchor changed, redirect chain present, temporary redirect, canonical missing, high outbound links, slow response, title missing, normalized target mismatch, footer/sidebar placement, JS-only link.

The detail page renders the **score breakdown** ("started at 100, −60 SOURCE_404 → capped at 25") so every number is explainable.

### 8.9 Status & Issue Classification (enums)
**Overall status:** `PASS`, `WARNING`, `FAIL`, `UNKNOWN`, `NEEDS_MANUAL_REVIEW`.
- **FAIL** if any CRITICAL issue, or score < 30.
- **WARNING** if no CRITICAL but any HIGH/MEDIUM, or score 30–79.
- **PASS** if score ≥ 80 and no CRITICAL/HIGH.
- **UNKNOWN** if crawl yielded no verdict after retries (transient) and no prior data.
- **NEEDS_MANUAL_REVIEW** overrides PASS/WARNING when the core question can't be answered automatically (CAPTCHA/WAF, JS inconclusive, conflicting directives, content-type non-HTML).

**Issue labels (canonical set):** `LINK_MISSING, LINK_FOUND, LINK_NOFOLLOW, LINK_SPONSORED, LINK_UGC, PAGE_NOINDEX, PAGE_NOFOLLOW, X_ROBOTS_NOINDEX, X_ROBOTS_NOFOLLOW, ROBOTS_BLOCKED, CANONICAL_MISMATCH, CANONICAL_CROSS_DOMAIN, SOURCE_404, SOURCE_403, SOURCE_5XX, REDIRECT_CHAIN, REDIRECT_LOOP, WRONG_TARGET, ANCHOR_CHANGED, HTTP_ERROR, SSL_ERROR, TIMEOUT, DNS_ERROR, SOFT_404, CAPTCHA_DETECTED, JS_RENDER_REQUIRED, LINK_HIDDEN, TOO_MANY_OUTBOUND_LINKS, INDEXABILITY_UNKNOWN`. Each issue instance stores `{code, label, category, severity, message, recommendation, evidence}`.

### 8.10 Change Detection
On each crawl, diff against the latest stored result and emit typed history events: link removed/added, rel changed, anchor changed, index→noindex (or reverse), canonical changed, status-code changed, redirect-target changed, robots.txt changed, X-Robots changed, page became blocked / accessible again, **score changed**, **issue count changed**. Events feed the history timeline (§8.15) and alert rules (§8.12).

### 8.11 Monitoring & Scheduling
Manual single check; bulk check; **scheduled daily/weekly/monthly** per project (cron via Celery beat); **priority** checks; recheck **failed-only**, **warnings-only**; recheck **by project / vendor / campaign / tag**. Each backlink has `next_check_at`; scheduler enqueues due links with **domain-level throttling** and batching.

### 8.12 Alerts
Trigger when: backlink removed; dofollow→nofollow; page→noindex; page→robots-blocked; page→404/410/5xx; canonical→other page/domain; anchor changed; target changed; redirect issue appears; **score drops below threshold**. Channels: **in-app notifications** (built), **email** (structure ready), **Slack webhook** (structure ready), **generic webhook** (structure ready). Rules are per-project with severity filters & dedup/quiet-hours to avoid alert storms.

### 8.13 Dashboard
Totals: backlinks, pass/fail/warning/unknown counts, **avg QA score**; links lost today/week/month; nofollow / noindex / robots-blocked / canonical-issue / broken-page / redirect-issue counts; recently changed backlinks; **top failing domains**; **top vendors by failure rate**; **campaign performance**; client/project filters. Powered by materialized views for sub-2s loads at scale.

### 8.14 Backlink Table (data grid)
Search, multi-filter (status/issue/score/rel/indexability/robots/canonical/vendor/campaign/tag/date), sort, **keyset pagination** (1M-row safe), bulk actions (recheck/export/tag/assign), export selected, status & issue **badges**, columns: score, source URL, target URL, anchor, rel, HTTP status, indexability, canonical status, robots status, last checked, next check, assigned user, notes.

### 8.15 Backlink Detail Page
Full crawl result: source URL, final URL, target URL, link-found status, anchor, rel, HTTP status, **redirect chain**, meta robots, X-Robots-Tag, canonical, robots.txt result, indexability result, page-quality signals, **issue list (with severity + recommendation)**, **score breakdown**, **history timeline**, raw headers, extracted link HTML, rendered-vs-raw comparison (placeholder/diff), notes, **manual override**, **recheck button**.

### 8.16 Reporting
Exports: **CSV / XLSX / PDF**. Report types: client, campaign, failed-links, vendor, **monthly QA**, change-history. Columns: source URL, target URL, final URL, link status, HTTP status, rel, anchor, indexability, robots, canonical, issues, score, last checked, **recommendation**. PDF supports client branding (logo/name). Large exports run as background jobs with a download link.

### 8.17 Recommendations Engine
Deterministic mapping from `issue.code → recommendation template` (seen throughout §8.6), rendered with the link's specifics. Examples: *Link missing → "Ask publisher to restore the backlink"*; *Nofollow → "Request removal of rel=nofollow per agreement"*; *Noindex → "Page won't pass SEO value; request indexable placement"*; *Canonical mismatch → "Equity consolidates to the canonical URL; ensure it hosts/credits the link"*; *Robots blocked → "Search engines can't crawl this page; request unblock"*; *404 → "Backlink lost unless restored; seek replacement"*; *Redirect chain → "Verify final destination and reduce hops."* Each backlink's recommendations are aggregated, de-duplicated, and prioritized by severity for reports.

---

## 9. Non-Functional Requirements

### 9.1 Performance
- P95 API < 300 ms (non-aggregate); dashboard < 2 s; table query < 1 s via indexes + keyset pagination + materialized views.
- Single backlink HTTP check P50 < 3 s (raw), < 12 s (rendered).

### 9.2 Scalability (10k / 100k / 1M+)
- **10k:** single Postgres, 2–4 workers, Redis. Trivial.
- **100k:** batch inserts, per-domain token buckets, partition `crawl_results`/`backlink_history` by month, more workers, separate Playwright pool.
- **1M+:** Postgres **table partitioning** + read replicas; **queue sharding by domain hash**; raw HTML/snapshots in **object storage** (not DB); materialized views refreshed incrementally; optional **ClickHouse** for analytics; resumable imports & partial result saving; **horizontal worker autoscaling**; domain-level crawl throttling to stay polite.
- Cross-cutting: queue batching, rate limiting, retry/backoff, job status tracking, failure recovery.

### 9.3 Reliability
Idempotent crawl jobs; at-least-once processing with dedup; partial-result persistence; dead-letter queue; graceful degradation (raw-only if Playwright pool saturated); 99.9% availability target.

### 9.4 Security
Argon2 password hashing; short-lived JWT + refresh rotation; RBAC + tenant isolation on every query; input validation (Pydantic); SSRF protection on the crawler (block internal IP ranges/metadata endpoints); secrets via env/secret manager; per-IP & per-user rate limiting; TLS everywhere; CSRF-safe token handling; encrypted integration credentials.

### 9.5 Privacy & Compliance
Minimal PII (team accounts only); GDPR-style data export/delete for accounts; configurable history retention; tenant data isolation; full **audit logs**.

### 9.6 Compliance & Ethical Crawling (hard requirements)
Configurable, honest user-agent (with contact); **robots.txt awareness**; per-domain rate limiting & crawl-delay respect; request timeouts & max retries; **never overload a host**; **do not bypass** CAPTCHA/WAF/bot protection (detect → manual review); audit logs; permission system. (A "respect robots.txt for crawling" toggle is on by default; turning it off requires Admin and is logged.)

### 9.7 Observability
Structured JSON logs with correlation IDs; Prometheus metrics (crawl rate, success %, queue depth, per-domain throttling); Flower for Celery; error tracking (Sentry-ready); per-job timing.

### 9.8 Accessibility & i18n
WCAG AA target for UI; language/encoding detection on crawled pages; UTF-8 throughout; i18n-ready frontend (strings externalized).

---

## 10. Data Model Overview (full schema in Step 3)
Core tables: `users`, `workspaces`, `workspace_members`(role), `projects`, `project_members`, `vendors`, `campaigns`, `backlink_records`, `crawl_jobs`, `crawl_results`, `backlink_issues`, `backlink_history`, `notifications`, `alert_rules`, `reports`, `imports`(+`import_rows`), `settings`, `audit_logs`. Key indexes: `project_id`, normalized `source_url`, normalized `target_url`, `domain`, `status`, `score`, `last_checked_at`, `issue_type`, plus partitioning keys on results/history. (Detailed DDL, constraints, partitioning, and indexes come in Step 3.)

---

## 11. Integrations
**Now (structure ready):** Email (SMTP/provider), Slack webhook, generic webhook, Google Sheets (column-mapping import), API import.
**Later:** Ahrefs / Semrush / Majestic (backlink import + metrics enrichment), Google Search Console URL Inspection API (index verification), SSO/SAML, ticketing (Jira/Asana) for fix workflows. A normalized **import-mapping layer** is defined now so adding a provider = adding a mapper.

---

## 12. Sample Data & Import Format
**`sample_backlinks.csv`** (canonical headers; mapper accepts arbitrary headers → these):
```csv
source_url,target_url,expected_target_url,expected_anchor_text,expected_rel,campaign,vendor,client,cost,placement_date,expected_status,notes,tags
https://news-site.com/best-running-gear,https://acme.com/shoes,https://acme.com/shoes,best running shoes,dofollow,Q2 Outreach,LinkVendorX,Acme Co,150.00,2026-05-01,live,Guest post intro paragraph,"guest-post,tier1"
https://blog.example.org/review,https://acme.com/trail,https://acme.com/trail,trail running guide,dofollow,Q2 Outreach,OutreachPro,Acme Co,90.00,2026-05-04,live,In-content link,"editorial,tier2"
http://oldforum.test/thread/42,https://acme.com/community,https://acme.com/community,acme community,ugc,Forum Drops,ForumLinks,Acme Co,,2026-04-20,live,Forum signature,"forum,ugc"
```
A matching **seed dataset** (projects, vendors, campaigns, ~30 backlinks across PASS/WARNING/FAIL/UNKNOWN/REVIEW states with synthetic crawl results) will ship in Step 5 for instant demoing.

---

## 13. Assumptions, Constraints, Dependencies
- **Assumptions:** users supply the backlink list (we verify, not discover); publishers' pages are publicly reachable for most links; clients accept "indexability estimate" semantics.
- **Constraints:** we never bypass bot protection; rendered crawling is resource-heavy (separate pool); some hosts will be `UNKNOWN`/`REVIEW` and that's correct behavior.
- **Dependencies:** Postgres, Redis, object storage, Playwright/Chromium in worker image; outbound internet for crawling; optional third-party API keys.

---

## 14. Acceptance Criteria / Definition of Done (MVP)
1. A user can register, create a workspace/project, and import a CSV/XLSX with column mapping + per-row validation.
2. Imported links are URL-normalized, deduped, and queued; an import is resumable and reports row errors.
3. The crawler fetches source pages (raw, escalating to rendered), follows redirects, and persists full metadata + raw-HTML pointer.
4. All §8.6 checks run; each link gets issues (code/severity/explanation/recommendation), a 0–100 score with breakdown, and a status.
5. Followability & indexability are computed per §8.7 (including `UNKNOWN`/`REVIEW` handling).
6. Dashboard, table (filter/sort/keyset-paginate/bulk), and detail page render real data.
7. Change detection writes history; at least in-app alerts fire on regressions (email/Slack/webhook structurally ready).
8. CSV/XLSX/PDF exports work, including a client report.
9. Scheduled daily recheck runs via Celery beat with domain throttling.
10. RBAC enforced server-side; audit logs written; runs under Docker Compose.
11. Test suite (Step 9) passes for normalization, status/redirect/robots/meta/X-Robots/canonical/link/rel/anchor parsing, scoring, classification, and API endpoints.

### Tests required (Step 9 coverage map)
URL normalization · HTTP status detection · redirect chain parsing · robots.txt parsing · meta robots parsing · X-Robots parsing · canonical extraction · link detection (raw/rendered/hidden) · rel parsing · anchor comparison · scoring logic · issue classification · API endpoints.

---

## 15. Release Plan / Phasing
- **Phase 0 — MVP (Steps 5–10):** auth/RBAC, projects, import (CSV/XLSX/manual/paste), normalization, tiered crawler, full QA catalog, scoring, statuses, change detection, in-app + webhook/email/Slack alert structure, dashboard/table/detail, CSV/XLSX/PDF, daily schedule, Docker, tests, docs.
- **Phase 1:** GSC index verification, Ahrefs/Semrush/Majestic import, advanced anchor-profile analytics, saved views, scheduled report email delivery, proxy pool.
- **Phase 2:** SSO/SAML, ticketing integrations + outreach workflow, ML soft-404/spam classification, PDF link-text scanning, anomaly detection on score trends.
- **Enterprise:** K8s autoscaling, queue sharding, ClickHouse analytics, read replicas, SLA dashboards, white-label client portals.

---

## 16. Risks & Mitigations
| Risk | Mitigation |
|---|---|
| Bot protection blocks crawls → false "missing" | Detect CAPTCHA/WAF → `NEEDS_MANUAL_REVIEW`, never silent fail; rendered retry; honest UA. |
| JS-only links misjudged | Tiered render; record raw-vs-rendered; flag `JS_RENDER_REQUIRED`. |
| Crawling perceived as abusive | Robots.txt awareness, per-domain throttling, crawl-delay, conservative defaults, audit logs. |
| DB bloat at 1M | Object-storage HTML, partitioning, retention policies, materialized views. |
| Celery async mismatch | Internal async batch within tasks + separate Playwright pool; `arq` fallback documented. |
| SSRF via user-supplied URLs | Block internal/metadata IP ranges; allowlist schemes (http/https). |
| Alert storms | Dedup, severity filters, quiet hours, digest mode. |

---

## 17. Open Questions
1. Default policy for `sponsored`/`ugc` per campaign type — confirm defaults (proposed: paid=expects sponsored, editorial=treats as HIGH).
2. Trailing-slash matching default — strict vs lenient (proposed: **lenient**).
3. History/raw-HTML retention windows (proposed: 12 months history, 30 days raw snapshots).
4. Will clients (Viewers) log into the same app, or get a separate white-label portal (Phase 2)?
5. Which integration is first after MVP — GSC (indexing truth) vs Ahrefs import? (proposed: **GSC**.)

> These have sensible defaults baked in; building proceeds on the proposed answers unless you override.

---

## 18. Glossary
**Followable link** — link that passes SEO equity (rel + page-level follow + crawlable + discoverable). **Indexable page** — page eligible to be indexed by search engines. **Soft-404** — returns 200 but is effectively "not found"/parked. **X-Robots-Tag** — HTTP-header equivalent of meta robots. **Canonical** — `rel=canonical` URL that consolidates ranking signals. **UGC** — user-generated-content link. **Keyset pagination** — cursor pagination that stays fast on huge tables.

---

## 19. Roadmap (enterprise upgrades)
Crawler proxy pools & geo-distributed crawling → ML classifiers (soft-404, spam, hidden-link, neighborhood quality) → GSC/Bing index truth → backlink-tool ingestion & metric enrichment → outreach/ticketing fix loop → anomaly detection & forecasting on score trends → white-label client portals → K8s + queue sharding + ClickHouse + read replicas → SLA & uptime dashboards → SSO/SAML & SCIM.

---

### ✅ End of Step 1
**Next: Step 2 — System Architecture** (component diagram, async worker design, tiered-crawl data flow, queue/throttling model, deployment topology, and the Celery-vs-arq decision in depth).
