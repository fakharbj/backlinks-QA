"""Login IP whitelist — pure rule-resolution tests (no DB).

Precedence: user override > role override > master switch. Empty whitelist
never blocks (lockout safety). CIDR + exact IPs both match.
"""

from __future__ import annotations

import pytest

from app.core.errors import ValidationAppError
from app.services.login_ip_service import defaults, is_allowed, normalize_ips

UID = "11111111-1111-1111-1111-111111111111"


def rules(**over) -> dict:
    r = defaults()
    r["enabled"] = True
    r["ips"] = ["203.0.113.7", "10.1.0.0/24"]
    r["role_overrides"] = {}  # drop the seeded admin exemption unless a test wants it
    r.update(over)
    return r


def test_disabled_allows_everyone():
    r = rules(enabled=False)
    ok, _ = is_allowed(r, "8.8.8.8", UID, "viewer")
    assert ok


def test_enabled_blocks_unlisted_ip():
    ok, why = is_allowed(rules(), "8.8.8.8", UID, "viewer")
    assert not ok and "not in the whitelist" in why


def test_exact_ip_and_cidr_match():
    assert is_allowed(rules(), "203.0.113.7", UID, "viewer")[0]
    assert is_allowed(rules(), "10.1.0.99", UID, "viewer")[0]
    assert not is_allowed(rules(), "10.2.0.99", UID, "viewer")[0]


def test_role_exempt_beats_master():
    r = rules(role_overrides={"admin": "exempt"})
    assert is_allowed(r, "8.8.8.8", UID, "admin")[0]
    assert not is_allowed(r, "8.8.8.8", UID, "viewer")[0]


def test_user_override_beats_role():
    # Role says exempt, but this specific user is enforced → blocked off-list.
    r = rules(role_overrides={"admin": "exempt"}, user_overrides={UID: "enforce"})
    assert not is_allowed(r, "8.8.8.8", UID, "admin")[0]
    # And the inverse: master off, user enforced → still blocked off-list.
    r2 = rules(enabled=False, user_overrides={UID: "enforce"})
    assert not is_allowed(r2, "8.8.8.8", UID, "viewer")[0]
    assert is_allowed(r2, "203.0.113.7", UID, "viewer")[0]


def test_user_exempt_beats_everything():
    r = rules(user_overrides={UID: "exempt"})
    assert is_allowed(r, "8.8.8.8", UID, "viewer")[0]


def test_empty_whitelist_never_locks_out():
    r = rules(ips=[])
    ok, why = is_allowed(r, "8.8.8.8", UID, "viewer")
    assert ok and "empty" in why


def test_missing_ip_blocked_when_enforced():
    assert not is_allowed(rules(), None, UID, "viewer")[0]


def test_normalize_ips_validates():
    assert normalize_ips([" 203.0.113.7 ", "10.1.0.0/24", ""]) == ["203.0.113.7", "10.1.0.0/24"]
    with pytest.raises(ValidationAppError):
        normalize_ips(["not-an-ip"])


def test_team_mode_precedence():
    # Team override beats role; user override beats team.
    r = rules(role_overrides={"viewer": "exempt"})
    assert not is_allowed(r, "8.8.8.8", UID, "viewer", team_mode="enforce")[0]
    r2 = rules(user_overrides={UID: "exempt"})
    assert is_allowed(r2, "8.8.8.8", UID, "viewer", team_mode="enforce")[0]
    # Team exempt beats master-on.
    assert is_allowed(rules(), "8.8.8.8", UID, "viewer", team_mode="exempt")[0]


def test_clean_keeps_notes_only_for_existing_normalized_entries():
    from app.services.login_ip_service import _clean

    out = _clean({
        "enabled": True,
        "ips": ["203.0.113.7/32", "10.1.0.0/24"],
        "ip_notes": {"203.0.113.7": "office", "9.9.9.9": "gone", "bad": "x"},
        "bind_sessions": True,
    })
    assert out["ips"] == ["203.0.113.7", "10.1.0.0/24"]
    assert out["ip_notes"] == {"203.0.113.7": "office"}
    assert out["bind_sessions"] is True
