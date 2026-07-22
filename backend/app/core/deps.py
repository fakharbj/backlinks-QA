"""FastAPI dependencies: authentication, tenant/role resolution, RBAC guards.

Every protected route depends on ``get_auth_context`` which yields an
``AuthContext`` carrying the user, the active ``workspace_id``, the role, and the
set of project ids the principal may see (``None`` == all projects in workspace).
Mutating routes additionally depend on ``require(Permission.X)``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Annotated

import jwt
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.rbac import Permission, Role, has_permission, is_project_scoped
from app.core.redis import is_jti_revoked
from app.core.security import decode_token
from app.db.session import get_read_session, get_session
from app.models.project import ProjectMember
from app.models.user import User, WorkspaceMember

_bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    user: User
    workspace_id: uuid.UUID
    role: Role
    # None → access to every project in the workspace (Admin / unrestricted role).
    allowed_project_ids: set[uuid.UUID] | None = None
    token_jti: str | None = None
    extra: dict = field(default_factory=dict)

    def require(self, permission: Permission) -> None:
        if not has_permission(self.role, permission):
            raise PermissionDeniedError(
                f"Role '{self.role.value}' lacks permission '{permission.value}'"
            )

    def assert_project(self, project_id: uuid.UUID) -> None:
        if self.allowed_project_ids is not None and project_id not in self.allowed_project_ids:
            raise PermissionDeniedError("You do not have access to this project")

    def project_filter(self) -> set[uuid.UUID] | None:
        return self.allowed_project_ids


async def get_auth_context(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_read_session)],
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
) -> AuthContext:
    if creds is None or not creds.credentials:
        raise AuthenticationError("Missing bearer token")

    try:
        payload = decode_token(creds.credentials, expected_type="access")
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid access token") from exc

    jti = payload.get("jti")
    if jti and await is_jti_revoked(jti):
        raise AuthenticationError("Token has been revoked")

    user_id = uuid.UUID(payload["sub"])
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive")

    # Resolve workspace: header override (for multi-workspace users) or token claim.
    ws_claim = x_workspace_id or payload.get("ws")
    if not ws_claim:
        raise AuthenticationError("No active workspace")
    workspace_id = uuid.UUID(ws_claim)

    membership = (
        await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise PermissionDeniedError("You are not a member of this workspace")

    role = membership.role
    allowed_projects: set[uuid.UUID] | None = None
    if is_project_scoped(role):
        rows = (
            await db.execute(
                select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
            )
        ).scalars().all()
        # Viewers/interns MUST be scoped (no rows = see nothing); managers/QA
        # without explicit rows see all projects in their workspace.
        if role in (Role.VIEWER, Role.INTERN) or rows:
            allowed_projects = set(rows)

    return AuthContext(
        user=user,
        workspace_id=workspace_id,
        role=role,
        allowed_project_ids=allowed_projects,
        token_jti=jti,
    )


AuthCtx = Annotated[AuthContext, Depends(get_auth_context)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
ReadSession = Annotated[AsyncSession, Depends(get_read_session)]


def require(permission: Permission):
    """Dependency factory enforcing a single permission."""

    async def _dep(ctx: AuthCtx) -> AuthContext:
        ctx.require(permission)
        return ctx

    return _dep


def require_role(minimum: Role):
    async def _dep(ctx: AuthCtx) -> AuthContext:
        if ctx.role.rank < minimum.rank:
            raise PermissionDeniedError(f"Requires at least '{minimum.value}' role")
        return ctx

    return _dep
