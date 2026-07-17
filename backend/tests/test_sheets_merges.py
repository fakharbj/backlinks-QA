"""Merged-cell fill — a merged User/Date column must not orphan grouped links.

Regression: Google returns a vertically-merged block's value only in its top
cell; the rest come back blank, so links below the first in a group showed as
'no user' in the system even though the sheet clearly assigned them.
``_fill_merged_cells`` copies each merge's anchor value into its whole block.
"""

from __future__ import annotations

from app.integrations.google_sheets import _fill_merged_cells


def test_vertical_user_merge_fills_group():
    # Header + 3 rows; "Alex" is merged down column 0 for rows 1..3 (0-based
    # grid rows 1..4, end-exclusive 4). Google returns it only in row 1.
    grid = [
        ["User", "Link", "Type"],
        ["Alex", "https://a.com/1", "Web 2.0"],
        ["", "https://a.com/2", "Web 2.0"],
        ["", "https://a.com/3", "Web 2.0"],
    ]
    _fill_merged_cells(grid, [(1, 4, 0, 1)])  # rows 1-3, col 0
    assert [r[0] for r in grid[1:]] == ["Alex", "Alex", "Alex"]
    # Non-merged columns are untouched.
    assert grid[2][1] == "https://a.com/2"


def test_no_merges_is_noop_and_blanks_stay():
    grid = [["User", "Link"], ["Alex", "https://a.com/1"], ["", "https://a.com/2"]]
    _fill_merged_cells(grid, [])
    assert grid[2][0] == ""  # nothing to fill without a merge range


def test_blank_anchor_never_fills():
    grid = [["User", "Link"], ["", "https://a.com/1"], ["", "https://a.com/2"]]
    _fill_merged_cells(grid, [(1, 3, 0, 1)])
    assert grid[1][0] == "" and grid[2][0] == ""  # anchor empty → leave blank


def test_out_of_range_merge_is_safe():
    grid = [["User", "Link"], ["Alex", "https://a.com/1"]]
    _fill_merged_cells(grid, [(1, 99, 0, 1)])  # end row beyond the grid
    assert grid[1][0] == "Alex"  # no crash, fills what exists
