"""Projects API."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import Role, require_assessor, require_viewer
from app.models.orm import Assessment, Project, User
from app.models.schemas import ProjectCreate, ProjectResponse, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


async def _validate_system_owner(db: AsyncSession, system_owner_id: int | None) -> int | None:
    if system_owner_id is None:
        return None
    system_owner = await db.scalar(
        select(User).where(
            User.id == system_owner_id,
            User.role == Role.SYSTEM_OWNER,
            User.is_active.is_(True),
        )
    )
    if system_owner is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="system_owner_id must reference an active system_owner account",
        )
    return system_owner.id


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_viewer),
) -> list[ProjectResponse]:
    q = select(Project)
    # Keep legacy creator access while honoring the explicit FISMA assignment.
    if current_user["role"] == Role.SYSTEM_OWNER:
        q = q.where(
            or_(
                Project.owner_id == current_user["id"],
                Project.system_owner_id == current_user["id"],
            )
        )
    result = await db.execute(q.order_by(Project.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
) -> ProjectResponse:
    values = body.model_dump(exclude={"system_owner_id"})
    project = Project(
        **values,
        owner_id=current_user["id"],
        system_owner_id=await _validate_system_owner(db, body.system_owner_id),
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_viewer),
) -> ProjectResponse:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if (
        current_user["role"] == Role.SYSTEM_OWNER
        and project.owner_id != current_user["id"]
        and project.system_owner_id != current_user["id"]
    ):
        raise HTTPException(status_code=403, detail="Access denied")
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
) -> ProjectResponse:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    values = body.model_dump(exclude_unset=True)
    if "system_owner_id" in values:
        values["system_owner_id"] = await _validate_system_owner(db, values["system_owner_id"])
    for field, value in values.items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    finalized_assessment = await db.scalar(
        select(Assessment.id).where(
            Assessment.project_id == project_id,
            Assessment.finalization_status == "finalized",
        ).limit(1)
    )
    if finalized_assessment:
        raise HTTPException(
            status_code=409,
            detail="A project containing finalized assessments cannot be deleted",
        )
    await db.delete(project)
    await db.commit()
