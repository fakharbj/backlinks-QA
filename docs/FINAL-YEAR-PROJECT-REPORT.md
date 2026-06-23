# LinkSentinel
## An Enterprise-Grade Backlink Quality Assurance & Monitoring Platform

**A Final Year Project Report**

---

| | |
|---|---|
| **Project Title** | LinkSentinel — Backlink QA & Monitoring Platform |
| **Submitted by** | _[Your Name]_ |
| **Roll / Registration No.** | _[Your Roll No.]_ |
| **Degree / Program** | _[e.g., BSc Computer Science / BS Software Engineering]_ |
| **Supervisor** | _[Supervisor Name]_ |
| **Department** | _[Department of Computer Science]_ |
| **Institution** | _[University / College Name]_ |
| **Academic Session** | _[e.g., 2025–2026]_ |
| **Live Demo** | http://72.62.81.34.nip.io |

---

## Certificate

This is to certify that the project entitled **"LinkSentinel — Backlink QA & Monitoring Platform"** submitted by _[Your Name]_ in partial fulfilment of the requirements for the award of the degree of _[Degree]_ is a record of bona fide work carried out under my supervision. The contents of this report, in full or in part, have not been submitted to any other institute or university for the award of any degree.

**Supervisor:** ______________________   **Head of Department:** ______________________

**External Examiner:** ______________________   **Date:** ______________

---

## Declaration

I hereby declare that this project report is my own original work and that, to the best of my knowledge, it contains no material previously published or written by another person except where due reference is made. All external libraries and resources used are acknowledged in the References section.

**Signature:** ______________________   **Date:** ______________

---

## Acknowledgement

I would like to express my sincere gratitude to my supervisor _[Supervisor Name]_ for continuous guidance and support throughout this project. I am thankful to the Department of _[Department]_ for providing the resources and environment to complete this work, and to my family and peers for their encouragement.

---

## Abstract

Backlinks — hyperlinks from external websites pointing to a target site — remain one of the strongest ranking signals in search engine optimisation (SEO). Agencies and in-house SEO teams routinely purchase, earn, or build hundreds to thousands of backlinks per client, but verifying that each link is **live, followable, indexable, and pointing to the correct destination** is a tedious, error-prone manual task. Links silently break, get changed to `nofollow`, are removed by publishers, get blocked by `robots.txt`, or sit behind bot-protection — quietly destroying the SEO value the client paid for.

**LinkSentinel** is a production-grade, multi-tenant web platform that automates the entire backlink quality-assurance (QA) lifecycle. It crawls each backlink with a search-engine-like fetcher, runs a registry of approximately sixty deterministic technical-SEO checks across fourteen categories (network, HTTP, redirects, link presence, anchor text, `rel` attributes, meta-robots, `X-Robots-Tag`, canonical, `robots.txt`, content-type, page quality, bot-protection and indexability), computes a transparent 0–100 quality score, and classifies every link into one of five verdicts (PASS, WARNING, NEEDS_MANUAL_REVIEW, UNKNOWN, FAIL). Results feed a real-time dashboard, change-detection alerts, scheduled re-crawling, role-based team collaboration, and exportable client reports.

The system is built as a FastAPI modular monolith with an asynchronous SQLAlchemy/PostgreSQL data layer (using monthly table partitioning for time-series data), a Redis-backed Celery worker fleet for distributed crawling, a tiered HTTP-then-headless-browser crawler with full Server-Side-Request-Forgery (SSRF) protection, and a Next.js 14 single-page frontend. The platform was successfully deployed to a live Linux VPS. This report documents the problem domain, requirements, architecture, design decisions, implementation, testing, deployment, and results, and concludes with a viva-preparation question bank.

**Keywords:** Backlink QA, Technical SEO, Web Crawling, FastAPI, PostgreSQL, Celery, Distributed Systems, RBAC, SSRF, Materialized Views.

---

## Table of Contents

1. Introduction
2. Literature Review & Background
3. System Analysis (Requirements)
4. System Design
5. Technology Stack & Justification
6. Implementation
7. Testing & Validation
8. Deployment
9. Results & Discussion
10. Conclusion & Future Work
11. References
- Appendix A — Installation & User Guide
- Appendix B — Viva Voce: Questions & Answers
- Appendix C — Glossary

---

# Chapter 1 — Introduction

## 1.1 Background

Search engines such as Google rank web pages partly on the quantity and quality of **backlinks** — links from other websites. A backlink is treated as a "vote of confidence". However, not all links carry equal weight:

- A link with `rel="nofollow"`, `rel="sponsored"` or `rel="ugc"` may pass little or no ranking authority.
- A link on a page blocked by `robots.txt`, marked `noindex`, or returning an HTTP error passes no value because search engines cannot crawl or index it.
- A link whose anchor text or destination URL was changed after placement may no longer serve its purpose.
- A link that has been silently removed represents lost investment.

SEO agencies manage these links across many clients. Verifying them by hand — opening each URL, viewing source, checking the `rel` attribute, confirming the link target, inspecting meta tags — does not scale and is unreliable.

## 1.2 Problem Statement

> There is no affordable, all-in-one system that automatically and continuously verifies the technical health of backlinks at scale, explains *why* a link is failing in SEO terms, detects changes over time, and presents the findings to a collaborating team with role-based access and client-ready reporting.

Existing point tools either only check HTTP status (link-checkers), or are expensive enterprise suites bundled with unrelated features. SEO teams need a focused, transparent, **QA-grade** tool purpose-built for backlink verification.

## 1.3 Objectives

The objectives of LinkSentinel are to:

1. **Automate crawling** of backlinks using a fetcher that emulates a search-engine crawler (honouring `robots.txt`, following redirects, escalating to a headless browser for JavaScript-rendered pages).
2. **Run a comprehensive battery of technical-SEO checks** that determine whether each link is present, followable, indexable, and correctly targeted.
3. **Produce a transparent, deterministic quality score (0–100)** and a human-readable verdict for every link, with a full breakdown of contributing issues.
4. **Detect changes over time** (link lost, became `nofollow`, anchor changed, status changed) and raise configurable alerts.
5. **Support multi-tenant team collaboration** with role-based access control (Admin, Manager, QA, Viewer).
6. **Provide a real-time dashboard, bulk import, scheduled re-checking, and exportable reports** (CSV, XLSX, PDF).
7. **Be production-deployable** on commodity infrastructure.

## 1.4 Scope

**In scope:** backlink ingestion (CSV/XLSX/paste), crawling and rendering, ~60 QA checks, scoring and classification, change detection, alerts, dashboards, team/role management, reporting, scheduled monitoring, and deployment.

**Out of scope (delegated to optional third-party APIs):** proprietary off-page metrics such as Moz Domain Authority (DA) or Ahrefs Domain Rating (DR), which require paid data providers; LinkSentinel exposes an integration point for these rather than reproducing them.

## 1.5 Significance

LinkSentinel converts a manual, hours-long QA process into an automated, continuous, explainable pipeline. The transparency of its scoring (every point deduction is traceable to a named SEO issue) makes it usable as evidence in client reporting and disputes with link vendors.

## 1.6 Organisation of the Report

Chapter 2 reviews the domain and related work. Chapter 3 captures requirements. Chapter 4 details the architecture and design. Chapter 5 justifies the technology stack. Chapter 6 describes the implementation of each subsystem. Chapter 7 covers testing, Chapter 8 deployment, Chapter 9 results, and Chapter 10 the conclusion. Appendix B contains a detailed viva question bank.

---

# Chapter 2 — Literature Review & Background

## 2.1 Technical SEO Concepts Relevant to Backlinks

| Concept | Meaning | Why it matters to a backlink |
|---|---|---|
| **Followability** | Whether a link passes ranking signals | `nofollow`/`sponsored`/`ugc`, page-level `noindex`/`nofollow`, or a `robots.txt` block can neutralise a link |
| **Indexability** | Whether the *page hosting* the link can be indexed | A `noindex` page is not in the index, so its outgoing links are not counted |
| **Canonicalisation** | The `<link rel="canonical">` declaring the preferred URL | A cross-domain or mismatched canonical can move authority away from the page |
| **Redirects** | 3xx hops between request and final URL | Redirect chains, loops, or a redirected *target* dilute or break the link |
| **Anchor text** | The clickable text of the link | Changed or empty anchors reduce relevance signals |
| **`X-Robots-Tag`** | HTTP-header equivalent of meta-robots | Can set `noindex`/`nofollow` invisibly at the header level |
| **Soft-404 / parked** | A page that returns 200 but is effectively empty/error | The link exists technically but on a worthless page |

## 2.2 How Search Engines Evaluate a Link (synthesised model)

A link contributes ranking value only if **all** of the following hold:
1. The hosting page is fetchable (HTTP 200, not blocked by `robots.txt`).
2. The hosting page is indexable (no `noindex` via meta or header, sensible canonical).
3. The specific link is discoverable in the served HTML (or rendered DOM).
4. The link is followable (`rel` does not strip authority; page is not `nofollow`).
5. The link points to the intended target.

LinkSentinel encodes this model directly as composite "followability" and "indexability" computations.

## 2.3 Related Tools & Gap Analysis

- **Generic link checkers** (e.g., broken-link crawlers) only report HTTP status — they ignore `rel`, `noindex`, canonical, anchor, and bot-protection.
- **Enterprise SEO suites** (Ahrefs, SEMrush, Moz) provide backlink *discovery* and proprietary metrics but limited *QA workflow* (no per-link verdict with deduction breakdown, no team QA queue, no vendor accountability reporting).
- **Spreadsheets + manual checking** — the status quo for many agencies — do not scale and are not repeatable.

**Gap:** a focused, transparent, automated **QA** tool with explainable scoring, change detection, team roles, and client reporting. LinkSentinel fills this gap.

---

# Chapter 3 — System Analysis

## 3.1 Methodology

The project followed an **iterative, incremental (Agile-inspired) SDLC**. Work was broken into nine increments — core/config, database, crawler library, QA engine, API & services, worker fleet, frontend, integrations/reports, and deployment — each producing a runnable artifact. Requirements were elicited from the technical-SEO domain and a written Product Requirements Document (PRD).

## 3.2 Functional Requirements

| ID | Requirement |
|---|---|
| FR-1 | Users can register, log in, and log out (JWT-based). |
| FR-2 | A workspace owner (Admin) can invite users and assign one of four roles. |
| FR-3 | Users can create projects, each with a target domain and QA policy. |
| FR-4 | Users can import backlinks via CSV, XLSX, or pasted text with column mapping. |
| FR-5 | The system crawls each backlink, following redirects and respecting `robots.txt`. |
| FR-6 | The system escalates to a headless browser when a link is absent from raw HTML and the page is JavaScript-heavy. |
| FR-7 | The system runs ~60 QA checks and computes a 0–100 score and a verdict. |
| FR-8 | The system detects changes between crawls and records typed history events. |
| FR-9 | Users can define alert rules (by severity, event type, score drop) delivered in-app and via email/Slack/webhook. |
| FR-10 | A dashboard shows status totals, issue mix, lost links over time, and top failing domains/vendors. |
| FR-11 | The system re-crawls links on a schedule (with shorter intervals for failing links). |
| FR-12 | Users can generate and download CSV/XLSX/PDF reports. |
| FR-13 | Users can manually override a verdict with a reason (audited). |
| FR-14 | All sensitive actions are recorded in an audit log. |

## 3.3 Non-Functional Requirements

| ID | Requirement | Approach |
|---|---|---|
| NFR-1 Performance | Dashboard loads in < 2 s; grid paginates 1M+ rows | Keyset pagination, indexed live aggregates |
| NFR-2 Scalability | Crawl throughput scales horizontally | Domain-sharded Celery queues, stateless workers |
| NFR-3 Security | Credentials encrypted; SSRF-proof crawler | Argon2id, JWT+JTI denylist, Fernet, IP allow-listing |
| NFR-4 Reliability | At-least-once task processing | `acks_late`, idempotent writes, circuit breaker |
| NFR-5 Maintainability | Framework-free core libraries | `crawler/` and `qa/` import no web/queue framework |
| NFR-6 Multi-tenancy | Strict data isolation | `workspace_id` + project scope on every query |
| NFR-7 Politeness | Do not overload publishers | Per-domain token-bucket rate limiting, crawl-delay |

## 3.4 Feasibility

- **Technical:** all components use mature open-source technology (Python, PostgreSQL, Redis, Node.js); proven feasible by the working deployment.
- **Economic:** runs on a single low-cost VPS; no paid APIs required for core function.
- **Operational:** a single web UI replaces manual spreadsheets; learnable in minutes.

## 3.5 Principal Use Cases (textual)

**UC-Crawl-Backlink:** *Actor:* Scheduler/QA user. *Flow:* select backlink → fetch raw HTML (SSRF-guarded) → parse → if link absent & JS-likely, render with browser → run QA checks → score → classify → persist → diff against previous → emit history events → fire matching alerts.

**UC-Invite-Member:** *Actor:* Admin. *Flow:* enter name/email/role/password → system creates user (or links existing) and a workspace membership → audit-logged → member can sign in.

---

# Chapter 4 — System Design

## 4.1 Architectural Overview

LinkSentinel is a **modular monolith** (single deployable API process with clean internal module boundaries) plus a **separate worker fleet** for background crawling. This avoids premature microservice complexity while keeping CPU-heavy crawling off the request path.

```
                ┌───────────────┐
   Browser ───► │  Next.js 14   │  (SPA, TanStack Query)
                └──────┬────────┘
                       │ HTTPS /api/v1
                ┌──────▼────────┐
                │  Nginx /      │  reverse proxy (CloudPanel)
                │  CloudPanel   │
                └──────┬────────┘
            ┌──────────┴───────────┐
            ▼                      ▼
   ┌──────────────┐        ┌──────────────┐
   │  FastAPI API │        │  Static SPA  │
   │  (uvicorn)   │        └──────────────┘
   └──┬───────┬───┘
      │       │
      │       └──────────────► Redis ◄────────── Celery Beat (scheduler)
      │                         ▲  ▲
      ▼                         │  │ broker / rate-limits / denylist
 ┌─────────┐                    │  │
 │Postgres │◄───────────────────┼──┴── Celery Workers (crawl/qa/alerts/reports)
 │  16     │                    │           │
 └─────────┘                    │           ▼
                                │      Tiered Crawler
   Object Storage ◄────────────┘      (httpx → Playwright)
   (local disk / MinIO)
```

**Module boundaries inside the API:**

- `core/` — config, security, RBAC, dependencies, Redis helpers, middleware, metrics.
- `db/` — SQLAlchemy base, session, DDL (partitions/enums/views), seed.
- `models/` — ORM tables.
- `schemas/` — Pydantic request/response models.
- `crawler/` — **framework-free** fetching, normalisation, robots, parsing, detection, rendering, SSRF.
- `qa/` — **framework-free** check registry, scoring, classification, composite logic.
- `services/` — business logic (auth, backlinks, dashboard, team, reports, alerts…).
- `api/v1/` — thin HTTP routers.
- `workers/` — Celery app, tasks, dispatch.
- `integrations/` — object storage, notifiers.

The **framework-free** rule on `crawler/` and `qa/` means those libraries can be unit-tested in isolation and reused (e.g., in a CLI) without importing FastAPI or Celery.

## 4.2 The Crawling Pipeline (Algorithm)

```
crawl(backlink):
    url ← normalise(source_url)              # 9 normalisation rules
    assert_url_allowed(url)                   # SSRF guard (DNS + IP checks)
    if respect_robots and robots.disallow(url): return BLOCKED
    raw ← fetch_raw(url)                       # httpx, capped size, manual redirects
    if circuit_open(domain): return UNKNOWN
    page ← parse_html(raw)                     # lxml/selectolax
    flags ← detect(raw)                        # captcha / WAF / soft-404 / parked
    match ← find_link(page, target)            # presence, rel, anchor
    if link_absent and js_heavy and browser:
        rendered ← render(url)                 # Playwright, SSRF-guarded routing
        re-parse, re-match on rendered DOM
    return CrawlArtifact(page, flags, match, redirect_chain, headers…)
```

**Tiering rationale:** ~90% of pages expose links in raw HTML and are handled by the cheap `httpx` path; only suspected JavaScript-rendered pages pay the cost of a headless browser, conserving CPU and memory.

## 4.3 URL Normalisation (9 rules)

Lower-case scheme/host; resolve relative URLs; remove default ports; decode/normalise percent-encoding; strip tracking parameters (`utm_*`, `gclid`, `fbclid`…); sort query parameters; handle IDN via Punycode; apply a configurable trailing-slash policy (strict/lenient); compute the registrable domain (eTLD+1) for grouping. Normalisation enables reliable de-duplication and link matching.

## 4.4 The QA Check Registry (≈60 checks, 14 categories)

Each check is a small pure function that inspects the `CrawlArtifact` and may emit zero or more **issues**. An issue has a `label`, a `category`, and a `severity` (CRITICAL, HIGH, MEDIUM, LOW, INFO).

| Code | Category | Example checks |
|---|---|---|
| NET | Network/DNS | DNS failure, connection refused, TLS error, timeout |
| HTTP | HTTP status | 404/410/403/5xx, 429 rate-limited |
| RDR | Redirects | redirect loop, excessive hops, target redirected away |
| LNK | Link presence | link missing, found-only-after-render, wrong target |
| ANC | Anchor text | anchor changed, empty/generic anchor |
| REL | Rel attribute | nofollow / sponsored / ugc |
| MR | Meta robots | `noindex`, `nofollow`, `none` |
| XR | X-Robots-Tag | header `noindex`/`nofollow` |
| CAN | Canonical | mismatch, cross-domain canonical |
| RBT | robots.txt | path disallowed |
| CT | Content-type | non-HTML response |
| PQ | Page quality | thin content, excessive outbound links, soft-404, parked |
| BOT | Bot-protection | CAPTCHA, WAF, Cloudflare challenge |
| IDX | Indexability | composite indexability unknown |

## 4.5 Scoring Algorithm (deterministic, transparent)

```
score = 100
for issue in issues:                 # deduction pass
    score -= severity_deduction(issue)   # CRITICAL 60, HIGH 25, MEDIUM 10, LOW 3, INFO 0
score = clamp(score, 0, 100)
for issue in issues:                 # hard-cap pass (lowest cap wins)
    score = min(score, severity_cap(issue))   # only CRITICAL caps, at 25
# label-specific caps (e.g., CAPTCHA_DETECTED caps at 25)
return score, breakdown              # breakdown lists every step for transparency
```

The two-pass design means a single CRITICAL issue (e.g., the link is missing) both deducts points *and* caps the maximum achievable score, so a broken link can never appear "mostly fine".

## 4.6 Verdict Classification (precedence)

```
FAIL              if a definite CRITICAL issue is present, or score < 30
NEEDS_MANUAL_REVIEW if captcha / WAF / non-HTML / conflicting directives
UNKNOWN           if transient error / 429 / 503 / 504 (retry later)
WARNING           if HIGH/MEDIUM issues present, or score < 80
PASS              otherwise
```

The precedence order (`FAIL → REVIEW → UNKNOWN → WARNING → PASS`) ensures bot-protected pages are routed to a human instead of being wrongly failed.

## 4.7 Database Design

**Core tables:** `users`, `workspaces`, `workspace_members`, `project_members`, `projects`, `vendors`, `campaigns`, `backlink_records`, `backlink_issues`, `crawl_results` *(partitioned)*, `backlink_history` *(partitioned)*, `crawl_jobs`, `alert_rules`, `notifications`, `reports`, `imports`, `import_rows`, `settings`, `audit_logs`, `refresh_tokens`, `password_reset_tokens`.

**Key design techniques:**

- **Monthly RANGE partitioning** on the high-volume, append-only time-series tables `crawl_results` and `backlink_history` (partition key in the composite primary key). Old months can be dropped cheaply; queries prune to the relevant partition. A maintenance task pre-creates future partitions.
- **Composite & partial indexes** on `backlink_records` — a grid index `(project_id, status, score)`, a keyset index `(project_id, score, id)` for constant-time pagination, a partial index `WHERE status='FAIL'`, and a GIN index on the `tags` array.
- **Live aggregation for dashboards** — status totals and issue-mix are computed directly from `backlink_records` so the dashboard never lags a crawl. (Materialized views remain defined for very large-scale rollups.)
- **Effective status** — `coalesce(override_status, status)` so a manual override transparently supersedes the computed verdict everywhere.

**Entity-relationship (textual):** a `workspace` has many `users` (through `workspace_members`) and many `projects`; a `project` has many `backlink_records`; a `backlink_record` has many `crawl_results` and `backlink_history` rows and a current set of `backlink_issues`; `vendors`/`campaigns` categorise backlinks for accountability reporting.

## 4.8 Security Design

- **Passwords:** Argon2id hashing (memory-hard).
- **Sessions:** short-lived access JWT (15 min) + rotating refresh JWT (7 days), each carrying a `jti`; logout/rotation revokes the `jti` via a Redis denylist; refresh-token reuse is detected and revokes the whole lineage.
- **Integration secrets** (SMTP/Slack/webhook): encrypted at rest with Fernet (envelope encryption).
- **SSRF defence:** the crawler only permits `http`/`https`; it resolves DNS and **blocks private, loopback, link-local, CGNAT, and cloud-metadata IP ranges**, and re-validates on every redirect hop and on browser sub-requests.
- **RBAC:** four roles (Admin, Manager, QA, Viewer) encoded in a single permission matrix; every query is scoped to `workspace_id` and (for restricted roles) an allowed-project set.

---

# Chapter 5 — Technology Stack & Justification

| Layer | Technology | Why chosen |
|---|---|---|
| Frontend | **Next.js 14 (App Router), React, TanStack Query, Tailwind CSS** | Modern SPA, server-rendered shell, simple data-fetching/caching, utility-first styling |
| API | **FastAPI + Pydantic v2 + Uvicorn/Gunicorn** | Async, type-safe, auto OpenAPI docs, high performance |
| ORM/DB | **SQLAlchemy 2.0 (async) + PostgreSQL 16 + Alembic** | Powerful relational features (partitioning, partial indexes, JSONB, enums), migrations |
| Queue | **Celery + Redis (+ RedBeat)** | Mature distributed task queue with scheduling and routing |
| Crawler | **httpx (async) + Playwright (Chromium)** | Cheap async fetch with optional real-browser rendering |
| Parsing | **lxml / selectolax** | Fast, lenient HTML parsing |
| Storage | **Local filesystem / MinIO (S3-compatible)** | Keeps large blobs out of Postgres; local default needs no extra service |
| Security | **Argon2, PyJWT, cryptography (Fernet)** | Industry-standard primitives |
| Process mgmt | **PM2** (deployment), **Docker Compose** (dev) | Keeps services alive; reproducible local stack |

**Why a modular monolith over microservices?** For a final-year-scale system, a monolith is simpler to develop, test, and deploy, while the clean module boundaries and the separate worker fleet preserve the main benefit microservices offer here (isolating heavy background work).

---

# Chapter 6 — Implementation

## 6.1 Backend Application Structure

The FastAPI app (`app/main.py`) wires middleware (correlation-id, CORS), exception handlers (uniform error envelope), the versioned router (`/api/v1`), and a `/healthz` probe. Settings are centralised in a Pydantic `BaseSettings` class so nothing reads environment variables ad-hoc.

## 6.2 Authentication & RBAC

`get_auth_context` is a FastAPI dependency that validates the bearer JWT, checks the Redis denylist, loads the user, resolves the active workspace and role, and computes the allowed-project set. Mutating endpoints additionally depend on `require(Permission.X)`, a dependency factory that enforces a single permission. This keeps authorisation declarative at the route layer.

## 6.3 Crawler Library (framework-free)

Implemented as pure modules: `normalize.py`, `ssrf.py`, `robots.py` (Googlebot-style longest-match evaluation with `*`/`$` wildcards), `fetch.py` (size-capped streaming with manual redirect following), `parse.py` (link extraction including HTML comments and hidden/region detection), `detect.py` (CAPTCHA/WAF/soft-404/parked signatures), `render.py` (Playwright with SSRF-guarded request routing), and `engine.py` (the orchestrating pipeline). None import FastAPI or Celery.

## 6.4 QA Engine (framework-free)

`registry.py` auto-loads all check functions; `engine.evaluate()` runs them, aggregates issues, calls `scoring.score_issues()` then `classification.classify()`, and produces composite followability/indexability and recommendations. A key correctness guard prevents a false "link missing" verdict when the page was unreadable (CAPTCHA/error/soft-404) — such pages are routed to manual review instead.

## 6.5 Worker Fleet

`celery_app.py` defines the queue topology: a `default` queue, domain-sharded `crawl.http.0–3` queues, an isolated `crawl.render` queue, and `qa`, `alerts`, `reports`, `maintenance` queues. The crawl task uses an event-loop-per-task pattern, holds **no** database session during network I/O, snapshots HTML to object storage, then persists each record in its own transaction (`acks_late` + idempotent writes make retries safe). A Beat schedule dispatches due re-crawls, refreshes dashboard rollups, rolls partitions forward, and runs retention cleanup.

## 6.6 Change Detection & Alerts

After each crawl, `result_service` diffs the new result against the previous one and emits typed `backlink_history` events (e.g., `link_removed`, `became_nofollow`, `anchor_changed`, `status_changed`, `score_changed`). `alert_service.evaluate()` matches active rules (by severity, event type, score-drop threshold), applies de-duplication and quiet hours, writes an in-app notification, and returns external-channel notifications for the worker to dispatch (HMAC-signed webhooks, Slack, SMTP).

## 6.7 Team & User Management (RBAC surface)

A dedicated `team` router exposes list/invite/role-change/activate/remove operations, all gated on the `MANAGE_USERS` permission and audit-logged. Service-layer guard-rails forbid demoting, deactivating, or removing the **last** Admin, or a user acting on their own account, preventing a workspace from locking itself out.

## 6.8 Frontend

A single-page application with a top-bar tab navigation (Overview, Backlinks, Imports, Alerts, Reports, Team), a project selector sidebar, and panels backed by TanStack Query. The Backlinks grid supports status filtering and opens a detail drawer with the score breakdown, issue list, redirect chain, and history timeline. Reports are downloaded as authenticated blobs.

---

# Chapter 7 — Testing & Validation

## 7.1 Strategy

Because the `crawler/` and `qa/` libraries are framework-free, they are covered by fast, deterministic **unit tests** that need no network or database. **Integration tests** exercise the API against a live Postgres/Redis stack and are skipped automatically when the stack is unavailable.

## 7.2 Representative Test Suites

| Suite | What it verifies |
|---|---|
| `test_normalize.py` | tracking-param stripping, relative resolution, scheme-insensitive matching, trailing-slash policy, IDN, registrable domain |
| `test_robots.py` | most-specific-group selection, `*`/`$` wildcards, longest-match wins, allow-on-tie |
| `test_parse.py` | link/footer/hidden/comment extraction, meta-robots & canonical, X-Robots most-restrictive combination |
| `test_checks.py` | 404/503, redirect loop, nofollow, anchor change, cross-domain canonical, meta/x-robots noindex, robots block, soft-404, captcha→review+cap, wrong target, JS-only, DNS error |
| `test_scoring.py` | empty=100, severity deductions, CRITICAL cap at 25, multiple-critical floor-then-cap, label cap, never negative |
| `test_security.py` | password hash round-trip, JWT round-trip & type enforcement, secret encryption round-trip |
| `test_api.py` | register → login → create project → create backlink → grid → dashboard → RBAC rejection |

## 7.3 Live Validation

The deployed system was validated by importing a real backlink set for the domain `techsadigital.com`. The crawler correctly produced differentiated verdicts: a genuine **PASS** (score 100, dofollow) for a ProvenExpert listing, **WARNING** (score 75, nofollow) for directory listings, and **NEEDS_MANUAL_REVIEW** (score 25, HTTP 403) for directory sites protected by bot-mitigation (Clutch, GoodFirms, DesignRush) — demonstrating that the bot-protection precedence rule works as designed (these are routed to a human, not falsely failed).

---

# Chapter 8 — Deployment

## 8.1 Target Environment

The system was deployed on a **Hostinger VPS running Debian 13**, managed with **CloudPanel**. Because the VPS provided Python 3.13, several pinned dependencies were upgraded to versions that ship pre-built wheels for 3.13 (notably `pydantic`/`pydantic-core`), and Playwright-based rendering was disabled on the server (the engine degrades gracefully, flagging JS-only pages for review).

## 8.2 Services (managed by PM2)

| Service | Role |
|---|---|
| `api` | Uvicorn running the FastAPI app on `127.0.0.1:8000` |
| `frontend` | Next.js production server on `127.0.0.1:3000` |
| `worker` | Celery worker consuming all queues |
| `beat` | Celery Beat / RedBeat scheduler |
| (PostgreSQL, Redis) | system services via `systemctl` |

CloudPanel's Nginx acts as a reverse proxy: `/api/` → `127.0.0.1:8000`, everything else → `127.0.0.1:3000`. A free `nip.io` wildcard hostname (`72.62.81.34.nip.io`) provides a domain that resolves to the server IP without registering one.

## 8.3 Deployment Pipeline

The project is under **Git** version control. Application code is transferred to the server; the backend restarts (`pm2 restart api worker`) and the frontend is rebuilt (`npm run build`) and restarted. No database migration is required for code-only changes; schema changes are applied with `alembic upgrade head`.

## 8.4 Notable Production Fixes (engineering log)

- Resolved Python-3.13 wheel incompatibilities by upgrading `pydantic`/`greenlet` and removing the optional Playwright pin.
- Fixed an `AmbiguousForeignKeys` ORM error by declaring `foreign_keys` on the `User.memberships` relationship (the `workspace_members` table has two foreign keys to `users`).
- Fixed a FastAPI "`Depends` in `Annotated` and default value together" error across all routers by using the plain `AuthContext` type with permission dependencies.
- Relaxed login email validation from strict `EmailStr` to `str` so internal/demo domains (`*.local`) are accepted (authentication is by exact lookup, not RFC deliverability).
- Replaced the stale materialized-view dashboard with **live aggregation**, eliminating all-zero dashboards.
- Added a **local-filesystem storage backend** so reports work on a single host without MinIO.

---

# Chapter 9 — Results & Discussion

The completed system meets all functional requirements:

- **Authentication, RBAC, and Team management** work end-to-end (Admin can invite Manager/QA/Viewer users).
- **Bulk import + crawling + QA** produce correct, differentiated verdicts on real-world links.
- **The Backlinks grid** displays status, score, source/target, HTTP status, `rel`, and the top issue per link.
- **The dashboard** shows live status totals and issue-mix.
- **Reports** generate as CSV/XLSX/PDF and download as authenticated files.
- **Alerts** can be configured and are evaluated after each crawl.

**Discussion:** the most valuable property of the system is **explainability** — every score is traceable to named SEO issues, which makes the output defensible in client reporting and vendor disputes. The bot-protection handling is a subtle but important correctness feature: many naive checkers would mark a 403 from Cloudflare as a failed link, whereas LinkSentinel correctly defers to human review.

**Limitations:** proprietary off-page metrics (DA/DR) require paid APIs; headless rendering was disabled on the demo server; the demo runs on a single node (the architecture supports horizontal scaling but this was not exercised).

---

# Chapter 10 — Conclusion & Future Work

## 10.1 Conclusion

LinkSentinel demonstrates a complete, production-grade backlink QA platform that automates an expensive manual workflow with transparent, explainable results. It applies real software-engineering practices — clean architecture, async I/O, distributed task processing, database partitioning, RBAC, defensive security (SSRF), and CI-style testing — to a genuine business problem, and was successfully deployed to a live server.

## 10.2 Future Work

1. **Authority integration** — pluggable Moz/Ahrefs/Majestic API for Domain Authority/Rating, surfaced as a per-domain column and filter.
2. **Analytics** — historical trend charts, vendor scorecards, and score-over-time graphs.
3. **Re-enable headless rendering** on a server with the required browser dependencies.
4. **Public link-status API & badge** for clients.
5. **Machine-learning soft-404/parked-page classifier** to complement the heuristic detector.
6. **Horizontal scale-out test** with PgBouncer and multiple worker nodes.

---

# References

1. Google Search Central — *Search Essentials* and *Crawling & Indexing* documentation.
2. Google — `robots.txt` specification and meta-robots / `X-Robots-Tag` documentation.
3. RFC 3986 — *Uniform Resource Identifier (URI): Generic Syntax*.
4. RFC 6761 — *Special-Use Domain Names*.
5. RFC 9110 — *HTTP Semantics* (status codes, redirects, headers).
6. OWASP — *Server-Side Request Forgery (SSRF) Prevention Cheat Sheet*.
7. OWASP — *Password Storage Cheat Sheet* (Argon2id).
8. FastAPI, SQLAlchemy 2.0, Pydantic v2, Celery, PostgreSQL 16, Next.js 14 — official documentation.
9. P. Biecek et al. / industry sources on technical SEO link evaluation (synthesised).

---

# Appendix A — Installation & User Guide

## A.1 Local Development (Docker)

```bash
git clone <repo> && cd backlinks-qa
cp .env.example .env
docker compose up --build
# API → http://localhost:8000/docs   UI → http://localhost:3000
```

## A.2 Production (VPS, no Docker)

1. Install PostgreSQL, Redis, Python 3, Node.js, and PM2.
2. Create the database and run `alembic upgrade head`, then `python -m app.db.seed`.
3. Start `api`, `worker`, `beat`, and `frontend` under PM2.
4. Configure Nginx to proxy `/api/` to the API and `/` to the frontend.

## A.3 Default Login (demo)

`admin@linksentinel.local` / `ChangeMe123!` (change immediately in production).

## A.4 Typical Workflow

Create a project → import backlinks (paste `source_url,target_url,…`) → wait for the worker to crawl → review verdicts in the Backlinks grid → open a link's detail for the score breakdown → configure alerts → invite teammates from the Team tab → generate a client report.

---

# Appendix B — Viva Voce: Questions & Answers

### B.1 General / Conceptual

**Q1. In one sentence, what is your project?**
A multi-tenant web platform that automatically crawls, checks, scores, and monitors the technical SEO health of backlinks, with team collaboration and client reporting.

**Q2. What is a backlink and why does its "quality" matter?**
A backlink is a hyperlink from another website to ours. Search engines treat it as a ranking signal, but only if the link is live, on a crawlable/indexable page, followable (not `nofollow`), and pointing to the right place. A link that looks fine to a human can be worthless to a search engine — that gap is what my project detects.

**Q3. What problem does it solve that a normal broken-link checker doesn't?**
A broken-link checker only reports HTTP status. Mine additionally checks `rel` attributes, meta-robots/`X-Robots-Tag` `noindex`, `robots.txt` blocking, canonical issues, anchor-text changes, redirects, bot-protection, and content quality — and explains *why* a link fails, with a transparent score.

**Q4. Who are the users?**
SEO agencies and in-house SEO teams. Roles: Admin (owns the workspace and team), Manager (runs projects), QA (does the link-checking work), Viewer (read-only client/stakeholder).

### B.2 Technical SEO Domain

**Q5. Difference between "followable" and "indexable"?**
*Indexable* describes the page hosting the link — can it be in the search index (not `noindex`, fetchable, sensibly canonicalised)? *Followable* describes the specific link — does it pass authority (`rel` not stripping it, page not `nofollow`, link discoverable)? A link only helps if both are true; I compute both as composite results.

**Q6. Why is a 403 from a site like Clutch shown as "Needs Manual Review" and not "Fail"?**
A 403 there is bot-protection (e.g., Cloudflare), not proof the link is gone — a real browser/user may see the link fine. Failing it would be a false negative, so my classification precedence routes bot-protected responses to human review instead.

**Q7. What does `rel="sponsored"` mean and how do you treat it?**
It marks a paid link. By policy it may pass no ranking authority. My system has a per-project setting (`treat_sponsored_as_follow`) because for a *paid campaign* the client often still wants the link present and indexable even if sponsored — so the policy is configurable rather than hard-coded.

**Q8. How do you check `robots.txt` correctly?**
I implement Google's matching rules: select the most *specific* User-agent group, support `*` and `$` wildcards, and apply the **longest-matching** rule, with Allow winning on an equal-length tie. Unknown/empty `robots.txt` means "allowed".

### B.3 Architecture & Design

**Q9. Why a modular monolith instead of microservices?**
For this scale, microservices add deployment and debugging complexity without real benefit. A monolith with clean module boundaries is simpler, and I still separate the CPU-heavy crawling into an independent Celery worker fleet — which is the one part that genuinely benefits from isolation and horizontal scaling.

**Q10. What does "framework-free core" mean and why did you do it?**
The `crawler/` and `qa/` packages import no FastAPI or Celery. That makes them unit-testable in isolation, reusable (e.g., from a CLI), and keeps business logic independent of delivery mechanism — a clean-architecture principle.

**Q11. Walk me through what happens when a backlink is crawled.**
Normalise the URL → SSRF-check it → check `robots.txt` → fetch raw HTML (size-capped, manual redirects) → parse → detect bot-protection/soft-404 → find the link and read its `rel`/anchor → if absent and the page looks JavaScript-rendered, render with a headless browser and re-check → run ~60 QA checks → score → classify → persist → diff against the previous crawl to emit history events → fire matching alerts.

**Q12. How is the system multi-tenant and how do you prevent data leaks between tenants?**
Every row carries a `workspace_id`, and every query is scoped to the caller's workspace (and, for restricted roles, an allowed-project set) inside the authentication dependency and service layer. There is no endpoint that returns data without that scope.

### B.4 Database

**Q13. Why did you partition some tables?**
`crawl_results` and `backlink_history` are append-only, high-volume, time-series tables. I use monthly RANGE partitioning so queries prune to the relevant month, indexes stay small, and old data can be dropped by detaching a partition instead of a slow mass `DELETE`. The partition key is part of the composite primary key, as PostgreSQL requires.

**Q14. What is keyset pagination and why use it over OFFSET?**
`OFFSET n` makes the database scan and discard `n` rows, which gets slower as users page deeper. Keyset pagination uses the last seen sort value + id as a cursor (`WHERE (sort,id) < (last_sort,last_id)`), so each page is an indexed range scan — constant time even at a million rows.

**Q15. You mentioned materialized views, then live queries — explain.**
Initially the dashboard read materialized views (cached summaries) for speed. In practice they were created when the table was empty and needed scheduled refreshes, which caused stale all-zero dashboards. For the current data scale I switched the dashboard to aggregate the live table directly — always correct, instant at this size. The materialized-view definitions remain for very large scale.

**Q16. What's a partial index and where did you use one?**
An index built over only a subset of rows. I index `backlink_records WHERE status='FAIL'`, because the most common operational query is "show me failing links", and the partial index is far smaller and faster than a full index.

### B.5 Security

**Q17. What is SSRF and how do you defend against it?**
Server-Side Request Forgery is tricking a server into fetching internal/forbidden resources (e.g., cloud metadata at `169.254.169.254`). Since my server fetches arbitrary user-supplied URLs, this is a real risk. I only allow `http`/`https`, resolve the hostname's IP, and block private/loopback/link-local/CGNAT/metadata ranges — and I re-validate on every redirect hop and on browser sub-requests, because a public URL can redirect to an internal one.

**Q18. How does your authentication work?**
Argon2id-hashed passwords; on login the server issues a 15-minute access JWT and a 7-day rotating refresh JWT, each with a unique `jti`. Logout or rotation adds the `jti` to a Redis denylist for O(1) revocation. If a refresh token is reused after rotation (a theft signal), I revoke the entire token lineage.

**Q19. Why Argon2 instead of, say, SHA-256 for passwords?**
SHA-256 is fast, which helps attackers brute-force. Argon2id is deliberately slow and memory-hard, making large-scale guessing impractical; it's the current OWASP-recommended password hash.

**Q20. How are third-party credentials (Slack token, SMTP password) stored?**
Encrypted at rest with Fernet (authenticated symmetric encryption); the key comes from configuration/KMS. They are never stored in plaintext.

### B.6 Backend / Async / Workers

**Q21. Why FastAPI and async?**
Crawling and the API are I/O-bound (waiting on network and database). Async lets a single process handle many concurrent requests/crawls without a thread per request. FastAPI also gives type-safe validation via Pydantic and auto-generated OpenAPI docs.

**Q22. Why Celery + Redis instead of crawling inside the request?**
Crawling is slow and bursty; doing it in the request would block the API and time out. Celery moves it to background workers, Redis is the message broker, and domain-sharded queues stop one busy domain from starving others.

**Q23. How do you make task processing reliable and safe to retry?**
Tasks use `acks_late` (acknowledged only after success) and idempotent writes (re-running produces the same result). A per-domain **circuit breaker** stops hammering a failing host, and a per-domain **token-bucket** rate-limiter (atomic Lua in Redis) keeps crawling polite.

**Q24. Why don't you hold a database connection while crawling?**
Crawling can take seconds; holding a DB connection that whole time would exhaust the pool. The worker loads what it needs in a short session, releases the connection, performs network I/O with no session, then opens a new short transaction to persist — maximising connection reuse.

### B.7 Frontend

**Q25. Why Next.js and TanStack Query?**
Next.js gives a fast, modern React app with a server-rendered shell. TanStack Query handles server-state caching, background refetching, and mutation invalidation declaratively, so the UI stays in sync with the API without manual state plumbing.

**Q26. How does report download work now?**
The download endpoint streams the file bytes with an `Authorization` header check; the frontend fetches it as a blob and triggers a browser download. This works with local file storage and keeps the download authenticated (no public/presigned URL needed).

### B.8 Deployment / DevOps

**Q27. How is it deployed and why nip.io?**
On a Debian VPS with CloudPanel; PostgreSQL/Redis run as system services and `api`/`worker`/`beat`/`frontend` run under PM2, behind CloudPanel's Nginx reverse proxy. `nip.io` is a free wildcard-DNS service that maps `<ip>.nip.io` to the IP, giving a working hostname without buying a domain.

**Q28. What was the hardest deployment problem and how did you solve it?**
The server's Python 3.13 had no pre-built wheels for the pinned `pydantic-core`, so `pip` tried to compile Rust and failed. I upgraded `pydantic`/`greenlet` to versions that ship 3.13 wheels and installed with `--prefer-binary`, eliminating compilation. I also fixed an ORM ambiguous-foreign-key error and a FastAPI dependency-declaration error that only surfaced at runtime.

**Q29. How do you push updates without breaking the running site?**
Code is version-controlled with Git; I deploy changed files, run an import smoke-test (`python -c "from app.main import app"`) **before** restarting the API to avoid a crash loop, then restart the worker and rebuild the frontend. Schema changes go through Alembic migrations.

### B.9 Testing & Quality

**Q30. How did you test something as messy as web crawling?**
By keeping the crawler and QA engine framework-free and feeding them fixture HTML/headers, so checks are tested deterministically without the network. Scoring and classification have table-driven unit tests; the API has an end-to-end integration test that runs when a database is available.

**Q31. Give an example of a tricky correctness case you handled.**
A page behind a CAPTCHA has no visible link, so a naive checker reports "link missing → FAIL". That's wrong — the link may exist for real users. My engine detects the unreadable page and routes it to manual review instead of fabricating a "missing link" failure.

### B.10 Scaling, Limitations, Ethics

**Q32. How would this scale to millions of links?**
Workers are stateless and horizontally scalable; queues are domain-sharded; the database uses partitioning, keyset pagination, and (at large scale) materialized views; PgBouncer can pool connections. You add worker nodes and the throughput grows.

**Q33. Is crawling other people's sites ethical/legal here?**
The crawler is polite: it honours `robots.txt`, applies per-domain rate limiting and crawl-delay, identifies itself with a User-Agent, caps response size, and only fetches URLs the user legitimately wants to QA (their own backlinks). It performs read-only GETs, like any search engine.

**Q34. What are the current limitations?**
Proprietary authority metrics (DA/DR) need paid APIs; headless rendering is disabled on the demo server; and the live demo runs on a single node. None are architectural limits — they are deployment/cost choices.

**Q35. If you had two more weeks, what would you add?**
A pluggable Domain-Authority integration, historical trend charts and vendor scorecards on the dashboard, and re-enabling headless rendering with the proper browser dependencies installed.

---

# Appendix C — Glossary

- **Backlink:** an inbound hyperlink from another site to the target site.
- **dofollow / nofollow:** whether a link passes ranking authority (`rel="nofollow"` asks search engines not to).
- **noindex:** a directive (meta tag or HTTP header) telling search engines not to index a page.
- **Canonical:** the `<link rel="canonical">` declaring the preferred URL for duplicate content.
- **Soft-404:** a page that returns HTTP 200 but is effectively an error/empty page.
- **SSRF:** Server-Side Request Forgery — abusing a server to make it fetch unintended resources.
- **RBAC:** Role-Based Access Control.
- **Keyset pagination:** cursor-based paging using the last row's sort key for constant-time pages.
- **Materialized view:** a stored, refreshable snapshot of a query's result.
- **Idempotent:** an operation that has the same effect whether run once or many times.
- **Circuit breaker:** a pattern that stops calling a failing dependency for a cool-down period.

---

*End of Report.*
