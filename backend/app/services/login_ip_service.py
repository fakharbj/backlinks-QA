"""Login IP whitelist (delivery hardening, 2026-07-22).

One Setting row (key="login_ip_rules") on the PRIMARY workspace (same
single-tenant resolution as branding — login happens before any workspace
context exists) controls who may SIGN IN and from where:

    {
      "enabled": false,                 # master switch
      "ips": ["1.2.3.4", "10.0.0.0/24"],  # exact IPs or CIDR networks (v4/v6)
      "user_overrides": {"<user_id>": "exempt"|"enforce"},
      "role_overrides": {"admin": "exempt", ...}
    }

Precedence (owner spec): user override > role override > master switch.
"exempt" = whitelist never applies to them (e.g. admins can log in from
anywhere); "enforce" = whitelist applies even when the master switch is off.

Lockout safety: an ENFORCED user with an EMPTY whitelist is allowed (an empty
list can never lock the whole company out), and the UI seeds admins as exempt.

Only /auth/login enforces this — an existing session (refresh token) keeps
working; the rule is about new sign-ins, per the owner brief.
"""

from __future__ import annotations

import ipaddress
import time
import uuid

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationAppError
from app.models.settings import Setting
from app.models.user import Workspace

KEY = "login_ip_rules"
_MODES = ("exempt", "enforce")


def defaults() -> dict:
    # Admins exempt out of the box — the owner's own example ("admin login
    # from any IP") and the guard against self-lockout when enabling.
    return {
        "enabled": False,
        "ips": [],
        # Optional remark per whitelist entry, keyed by the NORMALIZED entry
        # (normalize_ips output) so notes never silently detach.
        "ip_notes": {},
        # Explicit DENY list: an enforced user from a blocked IP/network is
        # rejected even if an allow entry also covers it (block wins).
        "blocked_ips": [],
        "blocked_notes": {},
        "user_overrides": {},
        "role_overrides": {"admin": "exempt"},
        # Keyed by a TeamLead's user id — applies to everyone on that lead's
        # team (labels via teamlead_users → employee mapping). Precedence:
        # user > team > role > master.
        "team_overrides": {},
        # When on, a session whose network address changes is revoked at the
        # next token refresh — the user must sign in again.
        "bind_sessions": False,
    }


def client_ip(request: Request) -> str | None:
    """The REAL client IP. Behind CloudPanel nginx ``request.client.host`` is
    127.0.0.1 — the vhost sets X-Real-IP; X-Forwarded-For's first hop is the
    fallback."""
    xr = (request.headers.get("x-real-ip") or "").strip()
    if xr:
        return xr
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def normalize_ips(ips: list[str]) -> list[str]:
    """Validate + normalise whitelist entries (single IPs or CIDR). Raises
    ValidationAppError naming the first bad entry."""
    out: list[str] = []
    for raw in ips:
        entry = (raw or "").strip()
        if not entry:
            continue
        try:
            net = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            raise ValidationAppError(f"'{entry}' is not a valid IP address or CIDR network.")
        out.append(str(net.network_address) if net.num_addresses == 1 else str(net))
    # De-dup, keep order.
    seen: set[str] = set()
    return [e for e in out if not (e in seen or seen.add(e))]


def _clean(payload: dict) -> dict:
    rules = defaults()
    rules["enabled"] = bool(payload.get("enabled", False))
    rules["bind_sessions"] = bool(payload.get("bind_sessions", False))
    rules["ips"] = normalize_ips(list(payload.get("ips") or []))
    rules["blocked_ips"] = normalize_ips(list(payload.get("blocked_ips") or []))
    # Notes survive only for entries that still exist, keyed by normalized form.
    notes_in = dict(payload.get("ip_notes") or {})
    normalized_notes: dict[str, str] = {}
    for k, v in notes_in.items():
        note = str(v or "").strip()[:120]
        if not note:
            continue
        try:
            key = normalize_ips([str(k)])[0]
        except (ValidationAppError, IndexError):
            continue
        if key in rules["ips"]:
            normalized_notes[key] = note
    rules["ip_notes"] = normalized_notes
    blocked_notes: dict[str, str] = {}
    for k, v in dict(payload.get("blocked_notes") or {}).items():
        note = str(v or "").strip()[:120]
        if not note:
            continue
        try:
            key = normalize_ips([str(k)])[0]
        except (ValidationAppError, IndexError):
            continue
        if key in rules["blocked_ips"]:
            blocked_notes[key] = note
    rules["blocked_notes"] = blocked_notes
    for field in ("user_overrides", "role_overrides", "team_overrides"):
        cleaned: dict[str, str] = {}
        for k, v in dict(payload.get(field) or {}).items():
            mode = str(v or "").strip().lower()
            if not mode:
                continue
            if mode not in _MODES:
                raise ValidationAppError(f"Override for '{k}' must be 'exempt' or 'enforce' (got '{v}').")
            cleaned[str(k)] = mode
        rules[field] = cleaned
    return rules


def is_allowed(
    rules: dict, ip: str | None, user_id: uuid.UUID | str, role: str,
    team_mode: str | None = None,
) -> tuple[bool, str]:
    """Pure decision: may this user log in from this IP? Returns (allowed, why).
    ``team_mode`` is the pre-resolved team override (async lookup — see
    resolve_team_mode); precedence: user > team > role > master."""
    mode = (rules.get("user_overrides") or {}).get(str(user_id))
    if mode is None:
        mode = team_mode
    if mode is None:
        mode = (rules.get("role_overrides") or {}).get(str(role or "").lower())
    if mode is None:
        mode = "enforce" if rules.get("enabled") else "exempt"
    if mode == "exempt":
        return True, "exempt"
    if not ip:
        return False, "client IP could not be determined"
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False, f"unparseable client IP '{ip}'"
    # Explicit block list wins over everything for an enforced user.
    for entry in rules.get("blocked_ips") or []:
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return False, f"IP is blocked ({entry})"
        except ValueError:
            continue
    ips = rules.get("ips") or []
    if not ips:
        return True, "whitelist empty — nothing to enforce"
    for entry in ips:
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True, f"matched {entry}"
        except ValueError:
            continue  # a bad stored entry never blocks evaluation of the rest
    return False, "IP not in the whitelist"


def explain(rules: dict, user_id, role: str, team_mode: str | None = None) -> dict:
    """Which layer decides for this user, and what mode results — powers the
    Settings tester ("which rule affects this user?"). Pure."""
    if str(user_id) in (rules.get("user_overrides") or {}):
        return {"layer": "user", "mode": rules["user_overrides"][str(user_id)]}
    if team_mode is not None:
        return {"layer": "team", "mode": team_mode}
    if str(role or "").lower() in (rules.get("role_overrides") or {}):
        return {"layer": "role", "mode": rules["role_overrides"][str(role or "").lower()]}
    return {"layer": "master", "mode": "enforce" if rules.get("enabled") else "exempt"}


def rules_can_enforce(rules: dict) -> bool:
    """Cheap short-circuit for the per-request hot path: can these rules
    possibly enforce for anyone? False = skip all work."""
    if rules.get("enabled"):
        return True
    for field in ("user_overrides", "role_overrides", "team_overrides"):
        if "enforce" in (rules.get(field) or {}).values():
            return True
    return False


# ── Per-request enforcement plumbing (hot path — cached, fail-open) ─────────
_RULES_CACHE: dict = {"rules": None, "ts": 0.0}
_TEAM_CACHE: dict[str, tuple[str | None, float]] = {}
_AUDIT_THROTTLE: dict[str, float] = {}
_CACHE_TTL = 20.0        # seconds — a settings save takes effect within this
_AUDIT_TTL = 300.0       # one audit row per (user, ip) per 5 min, not per request


def clear_rules_cache() -> None:
    _RULES_CACHE["rules"] = None
    _RULES_CACHE["ts"] = 0.0
    _TEAM_CACHE.clear()


async def get_rules_cached(db: AsyncSession) -> dict:
    now = time.monotonic()
    if _RULES_CACHE["rules"] is not None and now - _RULES_CACHE["ts"] < _CACHE_TTL:
        return _RULES_CACHE["rules"]
    rules = await get_rules(db)
    _RULES_CACHE["rules"] = rules
    _RULES_CACHE["ts"] = now
    return rules


async def team_mode_cached(db: AsyncSession, rules: dict, user_id) -> str | None:
    key = str(user_id)
    now = time.monotonic()
    hit = _TEAM_CACHE.get(key)
    if hit is not None and now - hit[1] < _CACHE_TTL:
        return hit[0]
    mode = await resolve_team_mode(db, rules, user_id)
    _TEAM_CACHE[key] = (mode, now)
    return mode


async def kill_sessions(user_id, *, ip: str | None, why: str, user_agent: str | None) -> None:
    """Session-death on IP violation: revoke EVERY refresh token the user
    holds (the old session can never renew) + one throttled audit row. Runs in
    its OWN session/commit — callable from read-only request dependencies."""
    throttle_key = f"{user_id}:{ip}"
    now = time.monotonic()
    if now - _AUDIT_THROTTLE.get(throttle_key, 0.0) < _AUDIT_TTL:
        return
    _AUDIT_THROTTLE[throttle_key] = now
    from app.db.session import session_scope
    from app.models.enums import AuditAction
    from app.services import audit_service, auth_service

    async with session_scope() as s:
        await auth_service._revoke_user_tokens(s, user_id)
        await audit_service.record(
            s, action=AuditAction.LOGOUT, actor_user_id=user_id,
            summary=f"Session revoked — IP no longer allowed ({ip}: {why})",
            ip_address=ip, user_agent=user_agent,
        )


async def resolve_team_mode(
    db: AsyncSession, rules: dict, user_id: uuid.UUID
) -> str | None:
    """Team-based access: if any TeamLead override covers this user (their
    sheet labels appear in that lead's team), return its mode. 'enforce' wins
    when several leads disagree. None when no team override applies."""
    overrides = {str(k): v for k, v in (rules.get("team_overrides") or {}).items()}
    if not overrides:
        return None
    from app.models.employee import UserEmployeeMapping
    from app.models.workforce import TeamLeadAssignment

    ws = await _primary_workspace_id(db)
    if ws is None:
        return None
    labels = [
        (lbl or "").strip().lower()
        for lbl in (
            await db.execute(
                select(UserEmployeeMapping.sheet_user_label).where(
                    UserEmployeeMapping.workspace_id == ws,
                    UserEmployeeMapping.user_id == user_id,
                    UserEmployeeMapping.canonical_label.is_(None),
                )
            )
        ).scalars().all()
        if lbl and lbl.strip()
    ]
    if not labels:
        return None
    lead_ids = (
        await db.execute(
            select(TeamLeadAssignment.manager_user_id).where(
                TeamLeadAssignment.workspace_id == ws,
                TeamLeadAssignment.member_label.in_(labels),
            ).distinct()
        )
    ).scalars().all()
    modes = {overrides[str(lid)] for lid in lead_ids if str(lid) in overrides}
    if not modes:
        return None
    return "enforce" if "enforce" in modes else "exempt"


async def _primary_workspace_id(db: AsyncSession) -> uuid.UUID | None:
    return (
        await db.execute(
            select(Workspace.id)
            .where(Workspace.is_active.is_(True))
            .order_by(Workspace.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_rules(db: AsyncSession) -> dict:
    ws = await _primary_workspace_id(db)
    if ws is None:
        return defaults()
    setting = (
        await db.execute(
            select(Setting).where(Setting.workspace_id == ws, Setting.key == KEY)
        )
    ).scalar_one_or_none()
    if setting is None or not isinstance(setting.value, dict):
        return defaults()
    merged = defaults()
    merged.update({k: setting.value.get(k, merged[k]) for k in merged})
    return merged


async def save_rules(db: AsyncSession, workspace_id: uuid.UUID, payload: dict) -> dict:
    """Validate + upsert onto the PRIMARY workspace (login is instance-wide;
    a non-primary workspace admin must not be able to plant login rules)."""
    primary = await _primary_workspace_id(db)
    if primary is None or primary != workspace_id:
        raise ValidationAppError("Login IP rules are managed from the primary workspace.")
    rules = _clean(payload)
    setting = (
        await db.execute(
            select(Setting).where(Setting.workspace_id == primary, Setting.key == KEY)
        )
    ).scalar_one_or_none()
    if setting is None:
        db.add(Setting(workspace_id=primary, key=KEY, value=rules, is_secret=False))
    else:
        setting.value = rules
    await db.flush()
    clear_rules_cache()  # per-request enforcement picks the change up at once
    return rules
