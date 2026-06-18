"""Raw DDL the ORM can't express: enum bootstrap, partitioning, materialized views.

Shared by the Alembic migration, the test bootstrap, and the maintenance worker so
there is exactly one definition of each.
"""

from __future__ import annotations

from app.core.rbac import Role
from app.models.enums import (
    AuditAction,
    CrawlMode,
    ExternalIndexStatus,
    HistoryEventType,
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    Indexability,
    IssueCategory,
    JobStatus,
    JobType,
    NotificationChannel,
    NotificationStatus,
    OverallStatus,
    ProjectStatus,
    RelType,
    ReportFormat,
    ReportStatus,
    ReportType,
    ScheduleInterval,
    Severity,
)

# (enum class, postgres type name) — the single source of truth for CREATE TYPE.
ENUM_TYPES = [
    (Role, "role_enum"),
    (ProjectStatus, "project_status_enum"),
    (ScheduleInterval, "schedule_interval_enum"),
    (RelType, "rel_type_enum"),
    (OverallStatus, "overall_status_enum"),
    (Indexability, "indexability_enum"),
    (ExternalIndexStatus, "external_index_status_enum"),
    (JobType, "job_type_enum"),
    (JobStatus, "job_status_enum"),
    (CrawlMode, "crawl_mode_enum"),
    (IssueCategory, "issue_category_enum"),
    (Severity, "severity_enum"),
    (HistoryEventType, "history_event_type_enum"),
    (ImportSource, "import_source_enum"),
    (ImportStatus, "import_status_enum"),
    (ImportRowStatus, "import_row_status_enum"),
    (ReportType, "report_type_enum"),
    (ReportFormat, "report_format_enum"),
    (ReportStatus, "report_status_enum"),
    (NotificationChannel, "notification_channel_enum"),
    (NotificationStatus, "notification_status_enum"),
    (AuditAction, "audit_action_enum"),
]

PARTITIONED_TABLES = ("crawl_results", "backlink_history")


def create_enum_sql() -> list[str]:
    statements: list[str] = []
    for enum_cls, name in ENUM_TYPES:
        labels = ", ".join(f"'{member.value}'" for member in enum_cls)
        statements.append(
            f"DO $$ BEGIN "
            f"IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{name}') THEN "
            f"CREATE TYPE {name} AS ENUM ({labels}); "
            f"END IF; END $$;"
        )
    return statements


# Partition-management function + default partitions. The maintenance worker calls
# ``ls_create_month_partition`` to roll partitions forward each month.
PARTITION_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION ls_create_month_partition(base_table text, ts timestamptz)
RETURNS void AS $$
DECLARE
    start_date date := date_trunc('month', ts)::date;
    end_date   date := (date_trunc('month', ts) + interval '1 month')::date;
    part_name  text := base_table || '_' || to_char(start_date, 'YYYYMM');
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = part_name) THEN
        EXECUTE format(
            'CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
            part_name, base_table, start_date, end_date
        );
    END IF;
END;
$$ LANGUAGE plpgsql;
"""


def default_partitions_sql() -> list[str]:
    out = []
    for tbl in PARTITIONED_TABLES:
        out.append(
            f"CREATE TABLE IF NOT EXISTS {tbl}_default PARTITION OF {tbl} DEFAULT;"
        )
    return out


def rolling_partitions_sql(months_back: int = 1, months_forward: int = 3) -> list[str]:
    """Pre-create monthly partitions around 'now' so the default stays empty."""
    out = []
    for tbl in PARTITIONED_TABLES:
        for offset in range(-months_back, months_forward + 1):
            out.append(
                f"SELECT ls_create_month_partition('{tbl}', "
                f"date_trunc('month', now()) + interval '{offset} month');"
            )
    return out


# ── Materialized views (Arch §10) ───────────────────────────────────────────────
# Effective status uses the manual override when present.
MATVIEWS_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_project_dashboard AS
SELECT
    b.project_id,
    b.workspace_id,
    count(*)                                                        AS total,
    count(*) FILTER (WHERE coalesce(b.override_status, b.status) = 'PASS')      AS pass_count,
    count(*) FILTER (WHERE coalesce(b.override_status, b.status) = 'WARNING')   AS warning_count,
    count(*) FILTER (WHERE coalesce(b.override_status, b.status) = 'FAIL')      AS fail_count,
    count(*) FILTER (WHERE coalesce(b.override_status, b.status) = 'UNKNOWN')   AS unknown_count,
    count(*) FILTER (WHERE coalesce(b.override_status, b.status) = 'NEEDS_MANUAL_REVIEW') AS review_count,
    count(*) FILTER (WHERE coalesce(b.override_status, b.status) = 'PENDING')   AS pending_count,
    round(avg(b.score) FILTER (WHERE b.score IS NOT NULL), 1)       AS avg_score,
    count(*) FILTER (WHERE b.current_rel = 'nofollow')             AS nofollow_count,
    count(*) FILTER (WHERE b.indexability = 'not_indexable')       AS noindex_count,
    count(*) FILTER (WHERE b.robots_status = 'blocked')            AS robots_blocked_count,
    count(*) FILTER (WHERE b.canonical_status IN ('mismatch','cross_domain')) AS canonical_issue_count,
    count(*) FILTER (WHERE b.http_status >= 400)                   AS broken_count,
    count(*) FILTER (WHERE b.link_found = false)                   AS link_missing_count,
    max(b.last_checked_at)                                          AS last_checked_at
FROM backlink_records b
GROUP BY b.project_id, b.workspace_id;

CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_project_dashboard
    ON mv_project_dashboard (project_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_vendor_failure_rates AS
SELECT
    b.vendor_id,
    b.workspace_id,
    count(*)                                                        AS total,
    count(*) FILTER (WHERE coalesce(b.override_status, b.status) = 'FAIL') AS fail_count,
    round(
        100.0 * count(*) FILTER (WHERE coalesce(b.override_status, b.status) = 'FAIL')
        / nullif(count(*), 0), 1)                                   AS failure_rate,
    round(avg(b.score) FILTER (WHERE b.score IS NOT NULL), 1)       AS avg_score
FROM backlink_records b
WHERE b.vendor_id IS NOT NULL
GROUP BY b.vendor_id, b.workspace_id;

CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_vendor_failure_rates
    ON mv_vendor_failure_rates (vendor_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_domain_failures AS
SELECT
    b.source_domain,
    b.workspace_id,
    count(*)                                                        AS total,
    count(*) FILTER (WHERE coalesce(b.override_status, b.status) = 'FAIL') AS fail_count,
    round(
        100.0 * count(*) FILTER (WHERE coalesce(b.override_status, b.status) = 'FAIL')
        / nullif(count(*), 0), 1)                                   AS failure_rate,
    round(avg(b.score) FILTER (WHERE b.score IS NOT NULL), 1)       AS avg_score
FROM backlink_records b
GROUP BY b.source_domain, b.workspace_id;

CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_domain_failures
    ON mv_domain_failures (workspace_id, source_domain);
"""

MATVIEW_NAMES = ("mv_project_dashboard", "mv_vendor_failure_rates", "mv_domain_failures")


def refresh_matviews_sql(concurrently: bool = True) -> list[str]:
    mode = "CONCURRENTLY " if concurrently else ""
    return [f"REFRESH MATERIALIZED VIEW {mode}{name};" for name in MATVIEW_NAMES]
