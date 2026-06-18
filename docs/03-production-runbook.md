# LinkSentinel Production Runbook

## Deployment

Run migrations before serving traffic:

```bash
docker compose run --rm api alembic upgrade head
docker compose up -d
```

For production, set `ENV_FILE=.env.production` or pass your orchestrator secrets as environment variables.

## Worker Pools

- `worker-http`: high-throughput raw HTTP crawling.
- `worker-render`: Playwright/Chromium render queue.
- `worker-default`: imports, alerts, reports, maintenance, and QA side work.
- `beat`: scheduled due rechecks, dashboard refresh, partition creation, retention cleanup.

Scale examples:

```bash
docker compose up -d --scale worker-http=4 --scale worker-render=2 --scale worker-default=2
```

## Backups

Back up:

- Postgres database.
- S3/MinIO buckets: `ls-snapshots`, `ls-reports`, `ls-imports`.
- Environment/secret configuration.

Recommended retention:

- Postgres PITR: at least 14 days.
- Crawl history: 365 days.
- Raw snapshots: 30 days.
- Audit logs: 730 days.

## Monitoring

Prometheus metrics are exposed by the API at `/metrics` when `PROMETHEUS_ENABLED=true`.

Track:

- API readiness `/readyz`.
- Celery queue depth and task failure rate.
- Crawl success/failure rate.
- Render escalation rate.
- Postgres connections and slow queries.
- Redis memory and key eviction.
- Object storage write failures.

## Incident Notes

If crawls stop:

1. Check Redis health.
2. Check `worker-http` logs.
3. Check Celery queues in Flower.
4. Confirm `beat` is dispatching `tasks.maintenance.dispatch_due_rechecks`.
5. Confirm DB migrations are current.

If reports fail:

1. Check object storage credentials and bucket access.
2. Check `worker-default` logs.
3. Confirm WeasyPrint system libraries are present in the image.

If alerts fail:

1. Check notification rows for `status=failed`.
2. Validate SMTP/webhook config.
3. Confirm outbound network egress is allowed from `worker-default`.
