"""SOC Audit Log API — NIST AU-2 / AU-3 / AU-6 / AU-12."""
import csv
import io
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_security_officer
from app.models.orm import AuditLog, User

router = APIRouter(prefix="/security/audit-logs", tags=["security"])

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _classify_severity(action: str, status_code: int) -> str:
    a = (action or "").lower()
    if status_code >= 500:
        return "critical"
    if status_code in (401, 423) or any(x in a for x in ["locked", "failed_login", "mfa_bypass", "breach"]):
        return "high"
    if status_code in (403, 400, 422) or "error" in a:
        return "medium"
    if status_code < 400 and any(x in a for x in ["login", "logout", "mfa", "token", "refresh"]):
        return "low"
    return "info"


def _classify_category(action: str, endpoint: str) -> str:
    text = ((action or "") + " " + (endpoint or "")).lower()
    if any(x in text for x in ["login", "logout", "mfa", "token", "refresh", "auth"]):
        return "AUTH"
    if any(x in text for x in ["user", "role", "permission", "access"]):
        return "ACCESS"
    if any(x in text for x in ["document", "assessment", "report", "artifact", "upload"]):
        return "DATA"
    if any(x in text for x in ["admin", "config", "setting"]):
        return "ADMIN"
    return "SYSTEM"


def _serialize_log(log: AuditLog, user: User | None) -> dict:
    return {
        "id": log.id,
        "timestamp": log.timestamp.isoformat(),
        "severity": _classify_severity(log.action, log.status_code),
        "category": _classify_category(log.action, log.endpoint),
        "action": log.action,
        "status_code": log.status_code,
        "method": log.method,
        "endpoint": log.endpoint,
        "user_id": log.user_id,
        "username": user.username if user else None,
        "email": user.email if user else None,
        "ip_address": log.ip_address,
        "user_agent": log.user_agent,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "metadata": log.request_body_summary,
    }


def _build_query(
    severity: str | None,
    category: str | None,
    action: str | None,
    start: datetime | None,
    end: datetime | None,
    user_id: int | None,
):
    q = (
        select(AuditLog, User)
        .outerjoin(User, AuditLog.user_id == User.id)
        .order_by(AuditLog.timestamp.desc())
    )
    if user_id:
        q = q.where(AuditLog.user_id == user_id)
    if action:
        q = q.where(AuditLog.action.ilike(f"%{action}%"))
    if start:
        q = q.where(AuditLog.timestamp >= start)
    if end:
        q = q.where(AuditLog.timestamp <= end)
    return q


@router.get("")
async def query_audit_logs(
    severity: str | None = Query(default=None),
    category: str | None = Query(default=None),
    action: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    user_id: int | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_security_officer),
) -> dict:
    q = _build_query(severity, category, action, start, end, user_id)

    # Count all matching (before client-side severity/category filter)
    count_q = select(func.count()).select_from(q.subquery())
    total_all = await db.scalar(count_q) or 0

    result = await db.execute(q.offset(offset).limit(limit * 3))  # fetch extra to filter by sev/cat
    rows = result.all()

    items = [_serialize_log(log, user) for log, user in rows]

    # Apply severity / category filter in Python (these are derived, not stored columns)
    if severity:
        items = [i for i in items if i["severity"] == severity.lower()]
    if category:
        items = [i for i in items if i["category"] == category.upper()]

    total = len(items)
    page_items = items[offset: offset + limit] if offset == 0 else items[:limit]

    # Severity breakdown for legend
    all_result = await db.execute(q.limit(5000))
    all_items = [_serialize_log(log, user) for log, user in all_result.all()]
    sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for i in all_items:
        sev_counts[i["severity"]] = sev_counts.get(i["severity"], 0) + 1

    return {
        "total": total,
        "total_all": total_all,
        "severity_counts": sev_counts,
        "offset": offset,
        "limit": limit,
        "items": page_items,
    }


@router.get("/export/csv")
async def export_csv(
    severity: str | None = Query(default=None),
    category: str | None = Query(default=None),
    action: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_security_officer),
) -> StreamingResponse:
    q = _build_query(severity, category, action, start, end, None)
    result = await db.execute(q.limit(10000))
    rows = result.all()
    items = [_serialize_log(log, user) for log, user in rows]
    if severity:
        items = [i for i in items if i["severity"] == severity.lower()]
    if category:
        items = [i for i in items if i["category"] == category.upper()]

    output = io.StringIO()
    fields = ["id", "timestamp", "severity", "category", "action", "status_code",
              "method", "endpoint", "username", "email", "ip_address", "resource_type", "resource_id"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(items)

    filename = f"soc-audit-log-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
