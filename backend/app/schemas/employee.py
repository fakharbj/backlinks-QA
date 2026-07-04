"""Employee code + mapping schemas (Phase 8, feature 3)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class AppUserOut(BaseModel):
    id: uuid.UUID
    name: str | None = None
    email: str


class EmployeeCodeOut(BaseModel):
    id: uuid.UUID
    code: str
    display_name: str | None = None
    user_id: uuid.UUID | None = None
    user_name: str | None = None
    is_active: bool


class EmployeeMappingOut(BaseModel):
    id: uuid.UUID
    sheet_user_label: str
    user_id: uuid.UUID | None = None
    user_name: str | None = None
    employee_code_id: uuid.UUID | None = None
    backlink_count: int = 0
    is_active: bool = True


class EmployeeOverviewOut(BaseModel):
    codes: list[EmployeeCodeOut] = []
    mappings: list[EmployeeMappingOut] = []
    app_users: list[AppUserOut] = []


class EmployeeCodeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=60)
    display_name: str | None = None
    user_id: uuid.UUID | None = None


class EmployeeCodeUpdate(BaseModel):
    display_name: str | None = None
    user_id: uuid.UUID | None = None
    is_active: bool | None = None


class EmployeeMappingUpdate(BaseModel):
    user_id: uuid.UUID | None = None
    employee_code_id: uuid.UUID | None = None
    # False = laid off: excluded from assignment pickers/planner/templates;
    # all historical work stays visible.
    is_active: bool | None = None
