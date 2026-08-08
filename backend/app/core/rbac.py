"""Role-based access control — FastAPI dependency helpers."""
from enum import StrEnum

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import TokenValidationError, decode_token

bearer_scheme = HTTPBearer()


class Role(StrEnum):
    SYSTEM_ADMIN = "system_admin"
    SECURITY_OFFICER = "security_officer"
    ASSESSOR = "assessor"
    REVIEWER = "reviewer"
    SYSTEM_OWNER = "system_owner"
    VIEWER = "viewer"


# Role hierarchy — higher index = more privilege
ROLE_HIERARCHY: list[str] = [
    Role.VIEWER,
    Role.SYSTEM_OWNER,
    Role.REVIEWER,
    Role.ASSESSOR,
    Role.SECURITY_OFFICER,
    Role.SYSTEM_ADMIN,
]


def _role_level(role: str) -> int:
    try:
        return ROLE_HIERARCHY.index(role)
    except ValueError:
        return -1


def _has_role(user_role: str, required: str) -> bool:
    return _role_level(user_role) >= _role_level(required)


# ── Token → current user payload ─────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Validate JWT and return payload dict with 'sub' and 'role'."""
    from sqlalchemy import select
    from app.models.orm import User

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise credentials_exception
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except TokenValidationError:
        raise credentials_exception

    # Verify user still active
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception

    return {"id": user.id, "username": user.username, "role": user.role, "email": user.email}


# ── Role requirement factories ────────────────────────────────────────────────

def require_role(minimum_role: str):
    """Returns a FastAPI dependency that enforces a minimum role level."""
    async def _check(current_user: dict = Depends(get_current_user)) -> dict:
        if not _has_role(current_user["role"], minimum_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {minimum_role} or higher",
            )
        return current_user
    return _check


# Convenience deps
require_viewer = require_role(Role.VIEWER)
require_system_owner = require_role(Role.SYSTEM_OWNER)
require_reviewer = require_role(Role.REVIEWER)
require_assessor = require_role(Role.ASSESSOR)
require_security_officer = require_role(Role.SECURITY_OFFICER)
require_admin = require_role(Role.SYSTEM_ADMIN)


async def require_project_access(
    project_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ensure the current user can access the project in the URL."""
    from sqlalchemy import select
    from app.models.orm import Project

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    if current_user["role"] == Role.SYSTEM_OWNER and project.owner_id != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return current_user


async def require_project_assessment_access(
    project_id: int,
    assessment_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ensure the current user can access the assessment in the URL."""
    from sqlalchemy import select
    from app.models.orm import Assessment, Project

    result = await db.execute(
        select(Assessment.id, Project.owner_id)
        .join(Project, Project.id == Assessment.project_id)
        .where(Assessment.id == assessment_id, Assessment.project_id == project_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assessment not found",
        )

    if current_user["role"] == Role.SYSTEM_OWNER and row.owner_id != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return current_user
