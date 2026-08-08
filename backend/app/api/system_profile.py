"""System Profile API — manage project system characteristics and derived N/A profile."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_assessor, require_project_access, require_viewer
from app.models.orm import SystemProfile
from app.services.controls.catalog import load_baseline
from app.services.system_profile import derive_na_controls, get_profile

router = APIRouter(
    prefix="/projects/{project_id}/system-profile",
    tags=["system-profile"],
    dependencies=[Depends(require_project_access)],
)


class SystemProfileRequest(BaseModel):
    deployment_model: str
    infrastructure_ownership: str = "org_owned"
    has_wireless_networking: bool = True
    has_external_connections: bool = True
    has_physical_facilities: bool = True
    has_mobile_devices: bool = True
    has_removable_media: bool = True
    user_population: str = "mixed"
    publicly_accessible: bool = True
    notes: str | None = None


def _to_dict(profile: SystemProfile, na_map: dict) -> dict:
    return {
        "id": profile.id,
        "project_id": profile.project_id,
        "deployment_model": profile.deployment_model,
        "infrastructure_ownership": profile.infrastructure_ownership,
        "has_wireless_networking": profile.has_wireless_networking,
        "has_external_connections": profile.has_external_connections,
        "has_physical_facilities": profile.has_physical_facilities,
        "has_mobile_devices": profile.has_mobile_devices,
        "has_removable_media": profile.has_removable_media,
        "user_population": profile.user_population,
        "publicly_accessible": profile.publicly_accessible,
        "notes": profile.notes,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        "created_by": profile.created_by,
        "na_controls": [
            {"control_id": cid, "rationale": rat}
            for cid, rat in sorted(na_map.items())
        ],
        "na_count": len(na_map),
    }


async def _get_na_map(project_id: int, profile: SystemProfile) -> dict[str, str]:
    from app.models.orm import Project
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if not project:
            return {}
    baseline = project.impact_baseline if project else "moderate"
    controls = load_baseline(baseline)
    return derive_na_controls(profile, controls)


@router.get("")
async def get_system_profile(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> dict:
    profile = await get_profile(project_id, db)
    if not profile:
        raise HTTPException(status_code=404, detail="No system profile set for this project")
    na_map = await _get_na_map(project_id, profile)
    return _to_dict(profile, na_map)


@router.post("", status_code=201)
async def create_system_profile(
    project_id: int,
    body: SystemProfileRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
) -> dict:
    existing = await get_profile(project_id, db)
    if existing:
        raise HTTPException(status_code=409, detail="Profile already exists — use PUT to update")
    profile = SystemProfile(
        project_id=project_id,
        created_by=current_user.get("username", "assessor"),
        **body.model_dump(),
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    na_map = await _get_na_map(project_id, profile)
    return _to_dict(profile, na_map)


@router.put("")
async def update_system_profile(
    project_id: int,
    body: SystemProfileRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
) -> dict:
    profile = await get_profile(project_id, db)
    if not profile:
        raise HTTPException(status_code=404, detail="No profile found — use POST to create")
    for field, value in body.model_dump().items():
        setattr(profile, field, value)
    await db.commit()
    await db.refresh(profile)
    na_map = await _get_na_map(project_id, profile)
    return _to_dict(profile, na_map)


@router.delete("", status_code=204)
async def delete_system_profile(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> None:
    profile = await get_profile(project_id, db)
    if profile:
        await db.delete(profile)
        await db.commit()
