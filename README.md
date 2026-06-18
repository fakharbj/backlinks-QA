# LinkSentinel

Enterprise backlink QA, monitoring, import, crawl, reporting, and alerting platform.

The repository now contains the runnable product surface:

- FastAPI backend with async SQLAlchemy, Alembic, RBAC, JWT auth, imports, crawler, QA engine, reports, alerts, and workers.
- Celery worker fleet split across HTTP crawl, render, reports, alerts, maintenance, and beat scheduling.
- Next.js operational dashboard for auth, projects, imports, backlinks, rechecks, alerts, and reports.
- Docker Compose stack with Postgres, Redis, MinIO, API, workers, beat, Flower, frontend, and nginx.
- Test suite covering URL normalization, robots.txt parsing, HTML/meta/X-Robots/canonical parsing, the QA check catalog, scoring, classification, auth/crypto primitives, report helpers, and an end-to-end API flow.

## Quick Start

```bash
docker compose up --build
```

Open:

- App: http://localhost
- API docs: http://localhost/docs
- MinIO console: http://localhost:9001
- Flower: http://localhost:5555

Optional demo data:

```bash
SEED_DEMO=true docker compose up --build
```

Demo login after seeding:

- Email: `admin@linksentinel.local`
- Password: `ChangeMe123!`

## No-Docker UI Demo

If Docker Desktop cannot start because BIOS virtualization is disabled, you can still
test the frontend workflow with the built-in mock API. This does not run Postgres,
Celery, crawling, or the production backend; it is only for clicking through the UI.

Terminal 1:

```bash
cd frontend
npm install
npm run mock-api
```

Terminal 2:

```bash
cd frontend
$env:NEXT_PUBLIC_API_BASE_URL="http://localhost:8000/api/v1"
npm run dev
```

Open http://localhost:3000 and sign in with any email/password, or use:

- Email: `admin@linksentinel.local`
- Password: `ChangeMe123!`

For production secrets, create `.env.production` from `.env.example` and run:

```bash
ENV_FILE=.env.production docker compose up -d --build
```

## Production Checklist

1. Set strong `JWT_SECRET`, `SECRETS_ENCRYPTION_KEY`, database password, Redis password, and object-storage credentials.
2. Put nginx behind TLS or replace it with a managed ingress/load balancer.
3. Use managed Postgres with automated backups and PITR.
4. Use managed Redis or Redis with persistence and memory limits.
5. Use real S3-compatible object storage for snapshots, reports, and imports.
6. Set an honest crawler user agent with a monitored contact address.
7. Set `DOCS_ENABLED=false` if public API docs are not acceptable.
8. Configure SMTP, Slack webhooks, or generic webhooks for external alerts.
9. Run `alembic upgrade head` during deployment before starting workers, or leave API startup migrations enabled for simple single-host deployments.
10. Scale workers independently: `worker-http` for throughput, `worker-render` for JS-heavy pages, `worker-default` for reports/alerts/maintenance.

## Useful Commands

```bash
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.db.seed
docker compose run --rm api-test
docker compose run --rm frontend-test
docker compose logs -f --tail=200
```

## Core Flow

1. Register or login at `/api/v1/auth`.
2. Create a project at `/api/v1/projects`.
3. Import backlinks via `/api/v1/imports/paste` or `/api/v1/imports/file`.
4. Workers process imports, create backlinks, and enqueue crawls.
5. Crawl workers fetch, parse, evaluate QA, persist issues/history, and enqueue alerts.
6. Dashboards and tables read denormalized current backlink state and materialized views.
7. Reports are generated asynchronously and stored in object storage.

## Architecture Docs

- [Product requirements](docs/01-product-requirements.md)
- [System architecture](docs/02-system-architecture.md)
- [Production runbook](docs/03-production-runbook.md)
