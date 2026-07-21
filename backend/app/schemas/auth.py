"""Auth & identity schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    workspace_name: str = Field(min_length=1, max_length=200)


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # access token TTL seconds


class WorkspaceSummary(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    role: str | None = None


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    avatar_data_uri: str | None = None


class MeResponse(BaseModel):
    user: UserOut
    workspaces: list[WorkspaceSummary]
    active_workspace_id: uuid.UUID | None = None
    role: str | None = None
