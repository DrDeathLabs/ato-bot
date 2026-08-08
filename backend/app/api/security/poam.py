"""POA&M management API — NIST CA-5."""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_security_officer
from app.models.orm import Assessment, POAM
from app.models.schemas import POAMCreate, POAMResponse, POAMUpdate

router = APIRouter(prefix="/security/poam", tags=["security"])


def _generate_poam_id(db_count: int) -> str:
    return f"POAM-{db_count + 1:04d}"


@router.get("", response_model=list[POAMResponse])
async def list_poam(
    status_filter: str | None = Query(default=None, alias="status"),
    risk_level: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_security_officer),
) -> list[POAMResponse]:
    q = select(POAM)
    if status_filter:
        q = q.where(POAM.status == status_filter)
    if risk_level:
        q = q.where(POAM.risk_level == risk_level)
    result = await db.execute(q.order_by(POAM.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=POAMResponse, status_code=status.HTTP_201_CREATED)
async def create_poam(
    body: POAMCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_security_officer),
) -> POAMResponse:
    if body.assessment_id:
        assessment = await db.scalar(select(Assessment).where(Assessment.id == body.assessment_id))
        if not assessment:
            raise HTTPException(status_code=404, detail="Assessment not found")
        if assessment.finalization_status == "finalized":
            raise HTTPException(status_code=409, detail="A finalized assessment's POA&M is immutable")
    count_result = await db.execute(select(POAM))
    count = len(count_result.scalars().all())
    poam = POAM(
        poam_id=_generate_poam_id(count),
        **body.model_dump(),
    )
    db.add(poam)
    await db.commit()
    await db.refresh(poam)
    return poam


@router.patch("/{poam_id}")
async def update_poam(
    poam_id: int,
    body: POAMUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_security_officer),
) -> dict:
    result = await db.execute(select(POAM).where(POAM.id == poam_id))
    poam = result.scalar_one_or_none()
    if not poam:
        raise HTTPException(status_code=404, detail="POAM entry not found")
    if poam.assessment_id:
        assessment = await db.scalar(select(Assessment).where(Assessment.id == poam.assessment_id))
        if assessment and assessment.finalization_status == "finalized":
            raise HTTPException(status_code=409, detail="A finalized assessment's POA&M is immutable")
    values = body.model_dump(exclude_unset=True)
    allowed_statuses = {"open", "in_progress", "completed", "accepted_risk", "closed"}
    if "status" in values and values["status"] not in allowed_statuses:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(allowed_statuses)}")
    if values.get("status") == "accepted_risk":
        rationale = str(values.get("acceptance_rationale") or poam.acceptance_rationale or "").strip()
        if len(rationale) < 20:
            raise HTTPException(status_code=422, detail="Risk acceptance requires a substantive rationale")
        poam.accepted_by = current_user["id"]
        poam.accepted_at = datetime.now(UTC)
    for key, value in values.items():
        setattr(poam, key, value)
    await db.commit()
    return {"detail": "Updated", "id": poam.id, "status": poam.status}
