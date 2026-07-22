"""Task-based source-domain recommendations (Phase 10 P4).

The engine answers one question: *given this person's task (project + link
types), which catalog domains should they use next?* Candidates come from the
workspace catalog MINUS everything unusable:

* domains the task's project already used (a link exists);
* robots-blocked domains (``robots_band`` fully/mostly blocked — owner rule:
  blocked domains never reach recommendations);
* spammy domains (spam_score ≥ ``_SPAM_CEILING``);
* domains whose opportunity workflow says blocked / rejected / archived for
  this project (``competitor_domain_decisions``);
* domains this person already accepted or skipped (no nagging).

Link-type fit is a RANKING BOOST, not a hard filter — a sparse catalog still
returns the best available domains, just ordered with matching types first.

Type matching is VARIANT-TOLERANT, because real data holds many spellings of
the same thing ("Web2.0", "WEB 2.0", "Web 2.o", "web-2.0", "GBP Web 2.0"…):

* wanted names are first expanded through the ``link_types`` alias layer
  (``merged_into_id`` — a merged misspelling matches its whole group);
* names are then normalized (lowercase, strip punctuation/spaces, digit-"o"
  → "0", so "Web 2.o" == "web2.0" == "WEB 2.0");
* an exact normalized match ranks highest; a "related" containment match
  ("gbpweb20" ⊃ "web20", "articlesubmission" ⊃ "article") ranks next.

Every row carries the domain's FULL link-type usage map + totals and human
``reasons`` so users see WHY it's suggested and what the domain was used for.
"""

from __future__ import annotations

import re
import uuid
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import NotFoundError, PermissionDeniedError, ValidationAppError
from app.models.recommendation import DomainRecommendation
from app.models.workforce import TaskAssignment

# Domains at/above this spam score never get recommended (Moz spam is 0-100;
# ≥30 is the same "risky" threshold the analytics spam KPI uses).
_SPAM_CEILING = 30
_BLOCKED_BANDS = ("fully_blocked", "mostly_blocked")
_ACTION_STATUSES = {"viewed", "accepted", "skipped"}
MAX_SUGGESTIONS = 50

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_DIGIT_O = re.compile(r"(?<=[0-9])o")  # "web 2.o" — the letter o used as zero


def link_type_tokens(names: list[str] | None) -> list[str]:
    """Lowercased, trimmed link-type names for tolerant JSONB-key matching."""
    return [n.strip().lower() for n in (names or []) if n and n.strip()]


def normalize_link_type(name: str | None) -> str:
    """Canonical comparison form of a link-type name: lowercase, strip every
    non-alphanumeric, then digit-adjacent "o"→"0". All of "Web2.0", "WEB 2.0",
    "Web 2.o", "web-2.0" become "web20". MUST stay in sync with the SQL
    twin in ``_suggest`` (same two regexps, applied in the same order)."""
    s = _NON_ALNUM.sub("", (name or "").lower())
    return _DIGIT_O.sub("0", s)


async def _expand_aliases(db: AsyncSession, workspace_id, names: list[str]) -> list[str]:
    """Widen wanted names through the link_types merge/alias layer: asking for
    any member of a merge group means every name in that group counts. Unknown
    names pass through unchanged. Returns the (deduped) widened name list."""
    if not names:
        return []
    rows = (
        await db.execute(
            text("SELECT id, name, merged_into_id FROM link_types WHERE workspace_id = :ws"),
            {"ws": workspace_id},
        )
    ).all()
    by_id = {r[0]: r for r in rows}

    def root_of(r) -> uuid.UUID:
        seen = set()
        while r[2] is not None and r[2] in by_id and r[0] not in seen:
            seen.add(r[0])
            r = by_id[r[2]]
        return r[0]

    groups: dict[uuid.UUID, list[str]] = {}
    for r in rows:
        groups.setdefault(root_of(r), []).append(r[1])
    by_lower = {r[1].strip().lower(): root_of(r) for r in rows}
    out: list[str] = []
    for n in names:
        out.append(n)
        root = by_lower.get(n.strip().lower())
        if root is not None:
            out.extend(groups.get(root, []))
    # Dedup, preserve order.
    seen: set[str] = set()
    return [x for x in out if not (x.strip().lower() in seen or seen.add(x.strip().lower()))]


def build_reasons(row: dict, wanted_types: list[str]) -> list[str]:
    """Human 'why this domain' strings — shown beside every suggestion."""
    out: list[str] = []
    matched_links = int(row.get("matched_links") or 0)
    match = row.get("match")
    if match == "exact" and matched_links:
        out.append(f"Used {matched_links}× for {row['matched_type']} links elsewhere")
    elif match == "related" and matched_links:
        out.append(f"Used {matched_links}× for the related type “{row['matched_type']}”")
    elif row.get("link_type_match"):
        out.append(f"Has {row['matched_type']} links elsewhere")
    elif wanted_types:
        out.append("No history for this link type yet — still meets quality checks")
    total = int(row.get("backlink_count") or 0)
    projects = int(row.get("project_count") or 0)
    if total and projects:
        out.append(f"{total} links built across {projects} project{'s' if projects != 1 else ''}")
    if row.get("da") is not None:
        out.append(f"DA {row['da']}")
    if row.get("spam_score") is not None and row["spam_score"] < 10:
        out.append("Low spam")
    if row.get("qualified_pct"):
        out.append(f"{round(row['qualified_pct'])}% of its links qualified")
    if (row.get("robots_band") or "allowed") == "allowed":
        out.append("Robots.txt allows crawling")
    out.append("Not used in this project yet")
    return out


async def _suggest(
    db: AsyncSession, ctx: AuthContext, *,
    project_id: uuid.UUID, link_types: list[str], user_label: str | None,
    limit: int,
) -> list[dict]:
    limit = max(1, min(limit, MAX_SUGGESTIONS))
    # Widen the wanted names through the alias/merge layer, then normalize —
    # matching happens on the normalized forms so every spelling variant of a
    # type ("Web2.0"/"WEB 2.0"/"Web 2.o"/"web-2.0") counts as the same thing.
    widened = await _expand_aliases(db, ctx.workspace_id, [n for n in (link_types or []) if n and n.strip()])
    wanted = link_type_tokens(widened)
    norm_wanted = sorted({normalize_link_type(n) for n in widened if normalize_link_type(n)})
    # One set-based query. Link-type fit via a LATERAL over the distribution
    # ENTRIES (key + count): tier 2 = exact normalized match, tier 1 = related
    # (one normalized name contains the other — catches "GBP Web 2.0" for a
    # "Web 2.0" task and "Article Submission" for "Article"). The SQL
    # normalizer MUST mirror ``normalize_link_type`` (same regexps, same
    # order). Exclusions stay NOT EXISTS so the planner can use the
    # (workspace, domain) indexes.
    sql = text(
        """
        SELECT sd.domain_key, sd.da, sd.pa, sd.spam_score, sd.semrush_as,
               sd.robots_band, sd.domain_age_days, sd.backlink_count,
               sd.indexed_count, sd.project_count, sd.user_count, sd.avg_score,
               sd.da_first, sd.pa_first, sd.market, sd.country,
               sd.link_type_distribution AS link_types,
               round(100.0 * sd.qualified_count / nullif(sd.backlink_count, 0), 1) AS qualified_pct,
               coalesce(m.tier, 0) > 0 AS link_type_match,
               CASE coalesce(m.tier, 0) WHEN 2 THEN 'exact' WHEN 1 THEN 'related' END AS match,
               m.matched_type, coalesce(m.matched_links, 0) AS matched_links
        FROM source_domains sd
        LEFT JOIN LATERAL (
            SELECT max(x.tier) AS tier,
                   (array_agg(x.k ORDER BY x.tier DESC, x.cnt DESC) FILTER (WHERE x.tier > 0))[1] AS matched_type,
                   sum(x.cnt) FILTER (WHERE x.tier > 0) AS matched_links
            FROM (
                SELECT e.key AS k,
                       coalesce(nullif(regexp_replace(e.value, '[^0-9]', '', 'g'), '')::bigint, 0) AS cnt,
                       (SELECT coalesce(max(CASE
                                WHEN nk.v = wt THEN 2
                                WHEN length(wt) >= 3 AND length(nk.v) >= 3
                                     AND (nk.v LIKE '%' || wt || '%' OR wt LIKE '%' || nk.v || '%') THEN 1
                                ELSE 0 END), 0)
                        FROM unnest(CAST(:norm_types AS text[])) wt) AS tier
                FROM jsonb_each_text(coalesce(sd.link_type_distribution, '{}'::jsonb)) e
                CROSS JOIN LATERAL (
                    SELECT regexp_replace(
                               regexp_replace(lower(e.key), '[^a-z0-9]+', '', 'g'),
                               '([0-9])o', '\\10', 'g') AS v
                ) nk
            ) x
            WHERE :n_types > 0
        ) m ON true
        WHERE sd.workspace_id = :ws
          AND coalesce(sd.robots_band, 'unknown') NOT IN ('fully_blocked', 'mostly_blocked')
          AND coalesce(sd.spam_score, 0) < :spam_ceiling
          AND NOT EXISTS (
              SELECT 1 FROM backlink_records b
              WHERE b.project_id = :pid AND b.source_domain = sd.domain_key)
          AND NOT EXISTS (
              SELECT 1 FROM competitor_domain_decisions d
              WHERE d.workspace_id = :ws AND d.project_id = :pid
                AND d.domain_key = sd.domain_key
                AND d.status IN ('blocked', 'rejected', 'archived'))
          AND (:label = '' OR NOT EXISTS (
              SELECT 1 FROM domain_recommendations r
              WHERE r.workspace_id = :ws
                AND coalesce(r.project_id, '00000000-0000-0000-0000-000000000000'::uuid)
                    = coalesce(:pid, '00000000-0000-0000-0000-000000000000'::uuid)
                AND r.domain_key = sd.domain_key AND r.recommended_to = :label
                AND r.status IN ('accepted', 'skipped')))
        ORDER BY coalesce(m.tier, 0) DESC,
                 coalesce(m.matched_links, 0) DESC,
                 sd.da DESC NULLS LAST,
                 round(100.0 * sd.qualified_count / nullif(sd.backlink_count, 0), 1) DESC NULLS LAST,
                 sd.spam_score ASC NULLS LAST, sd.domain_key ASC
        LIMIT :lim
        """
    )
    rows = (
        await db.execute(
            sql,
            {
                "ws": ctx.workspace_id, "pid": project_id,
                "norm_types": norm_wanted, "n_types": len(norm_wanted),
                "label": user_label or "", "spam_ceiling": _SPAM_CEILING, "lim": limit,
            },
        )
    ).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["matched_links"] = int(d.get("matched_links") or 0)
        d["reasons"] = build_reasons(d, wanted)
        out.append(d)
    return out


async def suggest_for_task(
    db: AsyncSession, ctx: AuthContext, assignment_id: uuid.UUID, *, limit: int | None = None
) -> dict:
    """Suggestions for ONE task — self-scoped: a viewer can only ask about their
    own assignments (visible_labels), a TeamLead about their people.

    Count rule (owner): no explicit limit → the task's assigned links + 2 spare
    picks — a 5-link task offers 7 domains, a 10-link task 12."""
    from app.services.workforce_service import visible_labels

    ta = await db.get(TaskAssignment, assignment_id)
    if ta is None or ta.workspace_id != ctx.workspace_id:
        raise NotFoundError("Task not found")
    scope = await visible_labels(db, ctx)
    if scope is not None and ta.user_label not in scope:
        raise PermissionDeniedError("Not your task")
    ctx.assert_project(ta.project_id)
    expected = int(ta.expected_links or 0)
    if limit is None:
        limit = expected + 2
    limit = max(1, min(limit, MAX_SUGGESTIONS))
    items = await _suggest(
        db, ctx, project_id=ta.project_id, link_types=ta.link_type_names or [],
        user_label=ta.user_label, limit=limit,
    )
    return {
        "assignment_id": str(assignment_id),
        "project_id": str(ta.project_id),
        "link_types": ta.link_type_names or [],
        "expected_links": expected,
        "suggestion_target": limit,
        "items": items,
    }


async def suggest_for_scope(
    db: AsyncSession, ctx: AuthContext, *,
    project_id: uuid.UUID, link_types: list[str] | None = None, limit: int = 20,
) -> dict:
    """Browse the engine without a task (admin/manager exploration)."""
    ctx.assert_project(project_id)
    items = await _suggest(
        db, ctx, project_id=project_id, link_types=link_types or [],
        user_label=None, limit=limit,
    )
    return {"project_id": str(project_id), "link_types": link_types or [], "items": items}


async def record_action(
    db: AsyncSession, ctx: AuthContext, *,
    domain_key: str, status: str, project_id: uuid.UUID | None = None,
    assignment_id: uuid.UUID | None = None, recommended_to: str | None = None,
    note: str | None = None, reason: str | None = None, link_type_name: str | None = None,
) -> DomainRecommendation:
    """A person acted on a suggestion (viewed/accepted/skipped) — upsert the row.
    Viewers act as themselves: when no label is passed, their own label is used."""
    from app.services.workforce_service import visible_labels

    if status not in _ACTION_STATUSES:
        raise ValidationAppError("status must be viewed, accepted or skipped")
    scope = await visible_labels(db, ctx)
    label = (recommended_to or "").strip()
    if scope is not None:
        if not label:
            if not scope:
                raise ValidationAppError("Your account isn't linked to a team member yet")
            label = sorted(scope)[0]
        elif label not in scope:
            raise PermissionDeniedError("Not your recommendation")
    existing = (
        await db.execute(
            select(DomainRecommendation).where(
                DomainRecommendation.workspace_id == ctx.workspace_id,
                DomainRecommendation.project_id == project_id,
                DomainRecommendation.domain_key == domain_key,
                DomainRecommendation.recommended_to == (label or None),
            )
        )
    ).scalars().first()
    if existing is None:
        existing = DomainRecommendation(
            workspace_id=ctx.workspace_id, project_id=project_id, domain_key=domain_key,
            assignment_id=assignment_id, recommended_to=label or None, source="auto",
        )
        db.add(existing)
    # viewed never downgrades an accept/skip decision.
    if not (status == "viewed" and existing.status in ("accepted", "skipped")):
        existing.status = status
    if note:
        existing.note = note[:300]
    # Skip workflow: keep WHY it was skipped (+ the link type when the reason
    # is a link-type problem) — reviewable later on the recommendations list.
    if reason:
        existing.reason = reason[:300]
    if link_type_name:
        existing.link_type_name = link_type_name[:80]
    if assignment_id is not None:
        existing.assignment_id = assignment_id
    existing.actor_user_id = ctx.user.id
    await db.flush()
    return existing


async def recommend_manual(
    db: AsyncSession, ctx: AuthContext, *,
    domain_key: str, user_label: str, project_id: uuid.UUID | None = None,
    assignment_id: uuid.UUID | None = None, link_type_name: str | None = None,
    priority: str | None = None, due_date: date | None = None,
    reason: str | None = None, note: str | None = None,
) -> DomainRecommendation:
    """Admin/manager hand-picks a domain for a person — clearly labeled MANUAL."""
    user_label = (user_label or "").strip()
    if not user_label:
        raise ValidationAppError("user_label is required")
    known = (
        await db.execute(
            text("SELECT 1 FROM source_domains WHERE workspace_id=:ws AND domain_key=:d LIMIT 1"),
            {"ws": ctx.workspace_id, "d": domain_key},
        )
    ).first()
    if known is None:
        raise NotFoundError("Domain is not in the source-domain catalog")
    existing = (
        await db.execute(
            select(DomainRecommendation).where(
                DomainRecommendation.workspace_id == ctx.workspace_id,
                DomainRecommendation.project_id == project_id,
                DomainRecommendation.domain_key == domain_key,
                DomainRecommendation.recommended_to == user_label,
            )
        )
    ).scalars().first()
    if existing is None:
        existing = DomainRecommendation(
            workspace_id=ctx.workspace_id, project_id=project_id, domain_key=domain_key,
            recommended_to=user_label,
        )
        db.add(existing)
    existing.source = "manual"
    existing.status = "suggested"
    existing.assignment_id = assignment_id
    existing.link_type_name = link_type_name
    existing.priority = priority
    existing.due_date = due_date
    existing.reason = (reason or "")[:300] or None
    existing.note = (note or "")[:300] or None
    existing.actor_user_id = ctx.user.id
    await db.flush()
    return existing


def _to_dict(r: DomainRecommendation) -> dict:
    return {
        "id": str(r.id), "project_id": str(r.project_id) if r.project_id else None,
        "domain_key": r.domain_key, "assignment_id": str(r.assignment_id) if r.assignment_id else None,
        "recommended_to": r.recommended_to, "link_type_name": r.link_type_name,
        "source": r.source, "status": r.status, "reason": r.reason,
        "priority": r.priority, "due_date": r.due_date.isoformat() if r.due_date else None,
        "note": r.note, "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


async def list_recommendations(
    db: AsyncSession, ctx: AuthContext, *,
    user_label: str | None = None, project_id: uuid.UUID | None = None,
    status: str | None = None, source: str | None = None,
    limit: int = 100, offset: int = 0,
) -> list[dict]:
    from app.services.workforce_service import visible_labels

    stmt = select(DomainRecommendation).where(
        DomainRecommendation.workspace_id == ctx.workspace_id
    )
    scope = await visible_labels(db, ctx)
    if scope is not None:
        stmt = stmt.where(DomainRecommendation.recommended_to.in_(scope or {""}))
    if user_label:
        stmt = stmt.where(DomainRecommendation.recommended_to == user_label)
    if project_id:
        stmt = stmt.where(DomainRecommendation.project_id == project_id)
    if status:
        stmt = stmt.where(DomainRecommendation.status.in_(
            [s for s in status.split(",") if s.strip()]
        ))
    if source in ("auto", "manual"):
        stmt = stmt.where(DomainRecommendation.source == source)
    stmt = stmt.order_by(DomainRecommendation.updated_at.desc()).limit(
        max(1, min(limit, 500))
    ).offset(max(0, offset))
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_dict(r) for r in rows]
