"""POA&M management API — NIST CA-5."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_assessor, require_security_officer, require_viewer
from app.models.orm import POAM
from app.models.schemas import POAMCreate, POAMResponse

router = APIRouter(prefix="/security/poam", tags=["security"])


def _generate_poam_id(db_count: int) -> str:
    return f"POAM-{db_count + 1:04d}"


@router.get("", response_model=list[POAMResponse])
async def list_poam(
    status_filter: str | None = None,
    risk_level: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
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
    _: dict = Depends(require_assessor),
) -> POAMResponse:
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
    status: str | None = None,
    remediation_plan: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_security_officer),
) -> dict:
    result = await db.execute(select(POAM).where(POAM.id == poam_id))
    poam = result.scalar_one_or_none()
    if not poam:
        raise HTTPException(status_code=404, detail="POAM entry not found")
    if status:
        poam.status = status
    if remediation_plan:
        poam.remediation_plan = remediation_plan
    await db.commit()
    return {"detail": "Updated"}
