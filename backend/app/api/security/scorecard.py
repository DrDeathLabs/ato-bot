"""Internal cATO scorecard API — NIST CA-7."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_security_officer, require_viewer
from app.models.orm import InternalControlStatus, POAM, SecurityEvent
from app.models.schemas import ScorecardSummary

router = APIRouter(prefix="/security/scorecard", tags=["security"])


@router.get("/summary", response_model=ScorecardSummary)
async def get_scorecard_summary(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> ScorecardSummary:
    result = await db.execute(select(InternalControlStatus))
    controls = result.scalars().all()

    counts = {"implemented": 0, "partially_implemented": 0, "not_implemented": 0,
              "inherited": 0, "not_applicable": 0}
    for c in controls:
        counts[c.status] = counts.get(c.status, 0) + 1

    total = len(controls)
    # Score: full credit for implemented/inherited/not_applicable, half for partial
    score_pts = (counts["implemented"] + counts["inherited"] + counts["not_applicable"] +
                 counts["partially_implemented"] * 0.5)
    compliance_score = round(score_pts / max(total, 1) * 100, 1)

    open_poams = await db.scalar(
        select(func.count(POAM.id)).where(POAM.status.in_(["open", "in_progress"]))
    )
    critical_events = await db.scalar(
        select(func.count(SecurityEvent.id)).where(
            SecurityEvent.severity == "critical", SecurityEvent.resolved == False
        )
    )

    return ScorecardSummary(
        total_controls=total,
        implemented=counts["implemented"],
        partially_implemented=counts["partially_implemented"],
        not_implemented=counts["not_implemented"],
        inherited=counts["inherited"],
        not_applicable=counts["not_applicable"],
        compliance_score=compliance_score,
        open_poams=open_poams or 0,
        critical_events_unresolved=critical_events or 0,
    )


@router.get("/controls")
async def list_control_statuses(
    family: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> list:
    q = select(InternalControlStatus)
    if family:
        q = q.where(InternalControlStatus.control_family == family.upper())
    result = await db.execute(q.order_by(InternalControlStatus.control_id))
    controls = result.scalars().all()
    return [
        {
            "control_id": c.control_id,
            "control_family": c.control_family,
            "control_title": c.control_title,
            "status": c.status,
            "auto_collected": c.auto_collected,
            "last_checked": c.last_checked.isoformat() if c.last_checked else None,
            "evidence_text": c.evidence_text,
        }
        for c in controls
    ]


@router.patch("/controls/{control_id}")
async def update_control_status(
    control_id: str,
    status: str,
    evidence_text: str | None = None,
    notes: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_security_officer),
) -> dict:
    from datetime import UTC, datetime
    result = await db.execute(
        select(InternalControlStatus).where(InternalControlStatus.control_id == control_id.upper())
    )
    ctrl = result.scalar_one_or_none()
    if not ctrl:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Control not found")
    ctrl.status = status
    if evidence_text is not None:
        ctrl.evidence_text = evidence_text
    if notes is not None:
        ctrl.notes = notes
    ctrl.auto_collected = False
    ctrl.updated_by = current_user["id"]
    ctrl.last_checked = datetime.now(UTC)
    await db.commit()
    return {"detail": "Updated"}
