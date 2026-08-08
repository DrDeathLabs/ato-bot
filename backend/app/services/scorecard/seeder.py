"""Seed ATO Bot's own NIST 800-53 internal control statuses on startup."""
import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import InternalControlStatus

logger = logging.getLogger(__name__)

_CONTROLS_FILE = Path(__file__).parent.parent.parent / "data" / "internal_controls" / "ato_bot_controls.json"


async def seed_internal_controls(db: AsyncSession) -> int:
    """Upsert ATO Bot internal controls from JSON seed. Returns count inserted/updated."""
    if not _CONTROLS_FILE.exists():
        logger.warning("Internal controls seed file not found: %s", _CONTROLS_FILE)
        return 0

    with open(_CONTROLS_FILE) as f:
        controls = json.load(f)

    count = 0
    for c in controls:
        result = await db.execute(
            select(InternalControlStatus).where(InternalControlStatus.control_id == c["control_id"])
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            db.add(InternalControlStatus(
                control_id=c["control_id"],
                control_family=c["control_family"],
                control_title=c["control_title"],
                status=c["status"],
                evidence_text=c.get("evidence_text"),
                notes=c.get("notes"),
            ))
            count += 1
        else:
            # Update title/description/components but preserve manually-set status
            existing.control_title = c["control_title"]
            existing.control_family = c["control_family"]
            if not existing.evidence_text:
                existing.evidence_text = c.get("evidence_text")
            if not existing.notes:
                existing.notes = c.get("notes")

    await db.commit()
    logger.info("Seeded %d internal controls", count)
    return count
