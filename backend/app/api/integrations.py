"""Project-scoped live connector management APIs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_assessor, require_project_access, require_viewer
from app.models.orm import Project
from app.services.integrations import (
    create_integration_account,
    delete_integration_account,
    get_integration_posture,
    list_connector_catalog,
    list_integration_accounts,
    list_integration_runs,
    run_integration_sync,
    test_integration_account,
)
from app.services.ato_bot_security import build_ato_bot_security_posture

router = APIRouter(
    prefix="/projects/{project_id}/integrations",
    tags=["integrations"],
    dependencies=[Depends(require_project_access)],
)


class IntegrationAccountCreate(BaseModel):
    connector_type: str
    name: str
    auth_mode: str = "dry_run"
    config_json: dict | None = None


async def _get_project_or_404(project_id: int, db: AsyncSession) -> None:
    exists = (await db.execute(select(Project.id).where(Project.id == project_id))).scalar_one_or_none()
    if not exists:
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/catalog")
async def connector_catalog(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return {"items": list_connector_catalog()}


@router.get("/accounts")
async def accounts(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await list_integration_accounts(project_id, db)


@router.get("/runs")
async def runs(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await list_integration_runs(project_id, db)


@router.get("/posture")
async def posture(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await get_integration_posture(project_id, db)


@router.get("/ato-bot-security")
async def ato_bot_security(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await build_ato_bot_security_posture(db)


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
async def create_account(
    project_id: int,
    payload: IntegrationAccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    await _get_project_or_404(project_id, db)
    try:
        return await create_integration_account(
            db,
            project_id=project_id,
            connector_type=payload.connector_type,
            name=payload.name,
            auth_mode=payload.auth_mode,
            config_json=payload.config_json,
            created_by=current_user["id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/accounts/{account_id}/test")
async def test_account(
    project_id: int,
    account_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
):
    await _get_project_or_404(project_id, db)
    result = await test_integration_account(db, project_id=project_id, account_id=account_id)
    if not result:
        raise HTTPException(status_code=404, detail="Connector account not found")
    return result


@router.post("/accounts/{account_id}/sync")
async def sync_account(
    project_id: int,
    account_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
):
    await _get_project_or_404(project_id, db)
    result = await run_integration_sync(db, project_id=project_id, account_id=account_id)
    if not result:
        raise HTTPException(status_code=404, detail="Connector account not found")
    return result


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    project_id: int,
    account_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> None:
    await _get_project_or_404(project_id, db)
    ok = await delete_integration_account(db, project_id=project_id, account_id=account_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Connector account not found")
