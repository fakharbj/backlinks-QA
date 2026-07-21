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
    return {"enabled": False, "ips": [], "user_overrides": {}, "role_overrides": {"admin": "exempt"}}


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
    rules["ips"] = normalize_ips(list(payload.get("ips") or []))
    for field in ("user_overrides", "role_overrides"):
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


def is_allowed(rules: dict, ip: str | None, user_id: uuid.UUID | str, role: str) -> tuple[bool, str]:
    """Pure decision: may this user log in from this IP? Returns (allowed, why)."""
    mode = (rules.get("user_overrides") or {}).get(str(user_id))
    if mode is None:
        mode = (rules.get("role_overrides") or {}).get(str(role or "").lower())
    if mode is None:
        mode = "enforce" if rules.get("enabled") else "exempt"
    if mode == "exempt":
        return True, "exempt"
    ips = rules.get("ips") or []
    if not ips:
        return True, "whitelist empty — nothing to enforce"
    if not ip:
        return False, "client IP could not be determined"
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False, f"unparseable client IP '{ip}'"
    for entry in ips:
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True, f"matched {entry}"
        except ValueError:
            continue  # a bad stored entry never blocks evaluation of the rest
    return False, "IP not in the whitelist"


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
    return rules
