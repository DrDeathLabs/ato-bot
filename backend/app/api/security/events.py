"""Security events feed API — NIST IR-6, SI-4."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_security_officer
from app.models.orm import SecurityEvent
from app.models.schemas import SecurityEventResponse

router = APIRouter(prefix="/security/events", tags=["security"])


@router.get("", response_model=list[SecurityEventResponse])
async def list_events(
    severity: str | None = Query(default=None),
    resolved: bool | None = Query(default=None),
    limit: int = Query(default=50, le=500),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_security_officer),
) -> list[SecurityEventResponse]:
    q = select(SecurityEvent).order_by(SecurityEvent.timestamp.desc())
    if severity:
        q = q.where(SecurityEvent.severity == severity)
    if resolved is not None:
        q = q.where(SecurityEvent.resolved == resolved)
    q = q.limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.patch("/{event_id}/resolve")
async def resolve_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_security_officer),
) -> dict:
    from datetime import UTC, datetime
    result = await db.execute(select(SecurityEvent).where(SecurityEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Event not found")
    event.resolved = True
    event.resolved_by = current_user["id"]
    event.resolved_at = datetime.now(UTC)
    await db.commit()
    return {"detail": "Event resolved"}
