from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_assessor, require_project_access, require_viewer
from app.models.orm import Project, SecurityCollector
from app.services.security_telemetry import (
    _build_change_events_domain,
    _build_configuration_domain,
    _build_data_protection_domain,
    _build_detections_domain,
    _build_identity_domain,
    _build_incidents_domain,
    _build_jobs_domain,
    get_control_support,
    get_live_state_payload,
    get_security_verifications,
    get_security_overview,
    ingest_build_snapshot_payload,
    ingest_security_payload,
    list_security_collectors,
    register_security_collector,
    run_security_verifications,
    rotate_security_collector_secret,
    verify_security_ingest_signature,
)

router = APIRouter(prefix="/projects/{project_id}/security", tags=["security-telemetry"])


class SecurityCollectorCreate(BaseModel):
    name: str
    collector_type: str = "local_runtime"
    metadata_json: dict | None = None


class BuildSnapshotCreate(BaseModel):
    label: str
    version: str | None = None
    commit_ref: str | None = None
    source: str = "manual_build"
    collected_at: str | None = None
    build_metadata: dict | None = None
    software_supply_chain: dict | None = None


async def _get_project_or_404(project_id: int, db: AsyncSession) -> None:
    exists = (await db.execute(select(Project.id).where(Project.id == project_id))).scalar_one_or_none()
    if not exists:
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/overview", dependencies=[Depends(require_project_access)])
async def security_overview(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await get_security_overview(project_id, db)


@router.get("/live-state", dependencies=[Depends(require_project_access)])
async def security_live_state(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await get_live_state_payload(project_id, db)


@router.get("/verifications", dependencies=[Depends(require_project_access)])
async def security_verifications(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await get_security_verifications(project_id, db)


@router.post("/verifications/run", dependencies=[Depends(require_project_access)])
async def security_run_verifications(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
):
    await _get_project_or_404(project_id, db)
    return await run_security_verifications(project_id, db)


@router.get("/control-support", dependencies=[Depends(require_project_access)])
async def security_control_support(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await get_control_support(project_id, db)


@router.get("/findings", dependencies=[Depends(require_project_access)])
async def security_findings(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    overview = await get_security_overview(project_id, db)
    return overview.get("findings", [])


@router.get("/recommendations", dependencies=[Depends(require_project_access)])
async def security_recommendations(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    overview = await get_security_overview(project_id, db)
    return overview.get("recommendations", [])


@router.get("/assets", dependencies=[Depends(require_project_access)])
async def security_assets(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    overview = await get_security_overview(project_id, db)
    return overview.get("assets", [])


@router.get("/identity", dependencies=[Depends(require_project_access)])
async def security_identity(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await _build_identity_domain(project_id, db)


@router.get("/configuration", dependencies=[Depends(require_project_access)])
async def security_configuration(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await _build_configuration_domain(project_id, db)


@router.get("/jobs", dependencies=[Depends(require_project_access)])
async def security_jobs(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await _build_jobs_domain(project_id, db)


@router.get("/data-protection", dependencies=[Depends(require_project_access)])
async def security_data_protection(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await _build_data_protection_domain(project_id, db)


@router.get("/change-events", dependencies=[Depends(require_project_access)])
async def security_change_events(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await _build_change_events_domain(project_id, db)


@router.get("/detections", dependencies=[Depends(require_project_access)])
async def security_detections(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await _build_detections_domain(project_id, db)


@router.get("/incidents", dependencies=[Depends(require_project_access)])
async def security_incidents(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await _build_incidents_domain(project_id, db)


@router.get("/build-snapshots", dependencies=[Depends(require_project_access)])
async def security_build_snapshots(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    overview = await get_security_overview(project_id, db)
    latest = overview.get("latest_build_snapshot")
    return [latest] if latest else []


@router.get("/collectors", dependencies=[Depends(require_project_access)])
async def collectors(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
):
    await _get_project_or_404(project_id, db)
    return await list_security_collectors(project_id, db)


@router.post("/collectors/register", dependencies=[Depends(require_project_access)], status_code=status.HTTP_201_CREATED)
async def register_collector(
    project_id: int,
    payload: SecurityCollectorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    await _get_project_or_404(project_id, db)
    return await register_security_collector(
        db,
        project_id=project_id,
        name=payload.name,
        collector_type=payload.collector_type,
        created_by=current_user["id"],
        metadata_json=payload.metadata_json,
    )


@router.post("/collectors/{collector_id}/rotate-secret", dependencies=[Depends(require_project_access)])
async def rotate_collector_secret(
    project_id: int,
    collector_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
):
    await _get_project_or_404(project_id, db)
    result = await rotate_security_collector_secret(db, project_id=project_id, collector_id=collector_id)
    if not result:
        raise HTTPException(status_code=404, detail="Collector not found")
    return result


@router.post("/build-snapshots", dependencies=[Depends(require_project_access)], status_code=status.HTTP_201_CREATED)
async def create_build_snapshot(
    project_id: int,
    payload: BuildSnapshotCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    await _get_project_or_404(project_id, db)
    collector = (
        await db.execute(
            select(SecurityCollector).where(
                SecurityCollector.project_id == project_id,
                SecurityCollector.collector_type == "manual_build",
            ).order_by(SecurityCollector.id.desc())
        )
    ).scalars().first()
    if not collector:
        created = await register_security_collector(
            db,
            project_id=project_id,
            name=f"Manual build snapshot by {current_user['username']}",
            collector_type="manual_build",
            created_by=current_user["id"],
            metadata_json={"managed": "manual_api"},
        )
        collector = await db.get(SecurityCollector, created["id"])
    return await ingest_build_snapshot_payload(
        db,
        project_id=project_id,
        collector=collector,
        payload=payload.model_dump(),
    )


@router.post("/ingest")
async def ingest_security(
    project_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_collector_id: int | None = Header(default=None, alias="X-Collector-Id"),
    x_collector_timestamp: str | None = Header(default=None, alias="X-Collector-Timestamp"),
    x_collector_nonce: str | None = Header(default=None, alias="X-Collector-Nonce"),
    x_collector_signature: str | None = Header(default=None, alias="X-Collector-Signature"),
):
    await _get_project_or_404(project_id, db)
    if not all([x_collector_id, x_collector_timestamp, x_collector_nonce, x_collector_signature]):
        raise HTTPException(status_code=401, detail="Missing collector authentication headers")
    body = await request.body()
    collector = await verify_security_ingest_signature(
        db,
        project_id=project_id,
        collector_id=x_collector_id,
        timestamp=x_collector_timestamp,
        nonce=x_collector_nonce,
        signature=x_collector_signature,
        body=body,
    )
    if not collector:
        await db.rollback()
        raise HTTPException(status_code=401, detail="Invalid collector signature")
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    return await ingest_security_payload(
        db,
        project_id=project_id,
        collector=collector,
        payload=payload,
    )


@router.post("/build-snapshots/ingest")
async def ingest_build_snapshot(
    project_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_collector_id: int | None = Header(default=None, alias="X-Collector-Id"),
    x_collector_timestamp: str | None = Header(default=None, alias="X-Collector-Timestamp"),
    x_collector_nonce: str | None = Header(default=None, alias="X-Collector-Nonce"),
    x_collector_signature: str | None = Header(default=None, alias="X-Collector-Signature"),
):
    await _get_project_or_404(project_id, db)
    if not all([x_collector_id, x_collector_timestamp, x_collector_nonce, x_collector_signature]):
        raise HTTPException(status_code=401, detail="Missing collector authentication headers")
    body = await request.body()
    collector = await verify_security_ingest_signature(
        db,
        project_id=project_id,
        collector_id=x_collector_id,
        timestamp=x_collector_timestamp,
        nonce=x_collector_nonce,
        signature=x_collector_signature,
        body=body,
    )
    if not collector:
        await db.rollback()
        raise HTTPException(status_code=401, detail="Invalid collector signature")
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    return await ingest_build_snapshot_payload(
        db,
        project_id=project_id,
        collector=collector,
        payload=payload,
    )
