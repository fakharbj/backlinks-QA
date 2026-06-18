"""Team / workspace-user management schemas (PRD §5).

A "team member" is the join of a ``User`` (identity) and a ``WorkspaceMember``
(their role within the active workspace). Email is a plain ``str`` rather than
``EmailStr`` so internal/special-use domains (e.g. ``*.local`` demo accounts)
are accepted — authentication is by exact lookup, not RFC deliverability.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.rbac import Role


class TeamMemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool
    last_login_at: datetime | None = None
    member_since: datetime


class TeamInvite(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    full_name: str = Field(min_length=1, max_length=200)
    role: Role = Role.VIEWER
    # Initial password the admin sets for the new member (no SMTP dependency).
    password: str = Field(min_length=10, max_length=128)


class TeamRoleUpdate(BaseModel):
    role: Role


class TeamActiveUpdate(BaseModel):
    is_active: bool
