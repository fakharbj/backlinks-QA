"""Intern role — permission-matrix and rank invariants (pure, no DB)."""

from __future__ import annotations

from app.core.rbac import Permission, Role, has_permission, is_project_scoped


def test_intern_rank_is_lowest():
    assert Role.INTERN.rank == 0
    assert all(Role.INTERN.rank < r.rank for r in (Role.VIEWER, Role.QA, Role.MANAGER, Role.ADMIN))


def test_intern_can_stage_and_check_but_never_approve_edit_or_export():
    assert has_permission(Role.INTERN, Permission.IMPORT_BACKLINKS)
    assert has_permission(Role.INTERN, Permission.RUN_CRAWLS)
    assert has_permission(Role.INTERN, Permission.VIEW_DASHBOARDS)
    assert not has_permission(Role.INTERN, Permission.EDIT_BACKLINKS)
    assert not has_permission(Role.INTERN, Permission.EXPORT_REPORTS)
    assert not has_permission(Role.INTERN, Permission.OVERRIDE_VERDICT)
    assert not has_permission(Role.INTERN, Permission.MANAGE_WORKSPACE)
    assert not has_permission(Role.INTERN, Permission.DELETE_RECORDS)


def test_intern_is_project_scoped():
    assert is_project_scoped(Role.INTERN)


def test_every_role_has_a_matrix_entry_and_rank():
    for r in Role:
        assert isinstance(r.rank, int)
        # role_permissions must not KeyError for any role.
        from app.core.rbac import role_permissions

        assert isinstance(role_permissions(r), set)
