"""Conflict scope classification — pure logic (no DB / no network)."""

from app.services.conflict_service import (
    CROSS_PROJECT,
    CROSS_USER,
    SAME_PROJECT,
    classify_scope,
)


def test_single_project_single_user_is_same_project():
    assert classify_scope(1, 1) == SAME_PROJECT


def test_multiple_projects_is_cross_project():
    assert classify_scope(2, 1) == CROSS_PROJECT


def test_project_spanning_wins_over_user_spanning():
    assert classify_scope(3, 5) == CROSS_PROJECT


def test_multiple_users_one_project_is_cross_user():
    assert classify_scope(1, 2) == CROSS_USER
