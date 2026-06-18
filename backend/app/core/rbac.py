"""Role-based access control (PRD §5).

Roles are workspace-scoped. Viewers (and optionally QA/Managers) may be further
restricted to specific projects via ``project_members``. This module is the
single source of truth for *what a role may do*; ``deps.py`` wires it into routes.
"""

from __future__ import annotations

import enum


class Role(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    QA = "qa"
    VIEWER = "viewer"

    @property
    def rank(self) -> int:
        return {"admin": 4, "manager": 3, "qa": 2, "viewer": 1}[self.value]


class Permission(str, enum.Enum):
    # workspace administration
    MANAGE_WORKSPACE = "manage_workspace"
    MANAGE_USERS = "manage_users"
    VIEW_AUDIT_LOGS = "view_audit_logs"
    MANAGE_INTEGRATIONS = "manage_integrations"
    # projects
    CREATE_PROJECT = "create_project"
    EDIT_PROJECT = "edit_project"
    DELETE_PROJECT = "delete_project"
    ASSIGN_MEMBERS = "assign_members"
    # vendors / campaigns
    MANAGE_VENDORS = "manage_vendors"
    # backlinks
    IMPORT_BACKLINKS = "import_backlinks"
    EDIT_BACKLINKS = "edit_backlinks"
    RUN_CRAWLS = "run_crawls"
    OVERRIDE_VERDICT = "override_verdict"
    # alerts / schedules
    CONFIGURE_ALERTS = "configure_alerts"
    # read
    VIEW_DASHBOARDS = "view_dashboards"
    EXPORT_REPORTS = "export_reports"


# The §5 matrix, encoded once. ``QA`` may *suggest* alert config but not commit
# it; that nuance is enforced at the service layer, not here.
_MATRIX: dict[Role, set[Permission]] = {
    Role.ADMIN: set(Permission),  # everything
    Role.MANAGER: {
        Permission.VIEW_AUDIT_LOGS,  # own projects only — narrowed in service layer
        Permission.CREATE_PROJECT,
        Permission.EDIT_PROJECT,
        Permission.DELETE_PROJECT,
        Permission.ASSIGN_MEMBERS,
        Permission.MANAGE_VENDORS,
        Permission.IMPORT_BACKLINKS,
        Permission.EDIT_BACKLINKS,
        Permission.RUN_CRAWLS,
        Permission.OVERRIDE_VERDICT,
        Permission.CONFIGURE_ALERTS,
        Permission.VIEW_DASHBOARDS,
        Permission.EXPORT_REPORTS,
    },
    Role.QA: {
        Permission.MANAGE_VENDORS,
        Permission.IMPORT_BACKLINKS,
        Permission.EDIT_BACKLINKS,
        Permission.RUN_CRAWLS,
        Permission.OVERRIDE_VERDICT,
        Permission.VIEW_DASHBOARDS,
        Permission.EXPORT_REPORTS,
    },
    Role.VIEWER: {
        Permission.VIEW_DASHBOARDS,
        Permission.EXPORT_REPORTS,
    },
}


def role_permissions(role: Role) -> set[Permission]:
    return _MATRIX[role]


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in _MATRIX[role]


def is_project_scoped(role: Role) -> bool:
    """Viewers are always project-scoped; managers/QA may be, admins never."""
    return role in (Role.VIEWER, Role.QA, Role.MANAGER)
