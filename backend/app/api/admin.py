"""Admin security dashboard metrics — real-time operational posture."""
import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_admin
from app.models.orm import AuditLog, Document, InternalControlStatus, SecurityEvent, User

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Storage cleanup ────────────────────────────────────────────────────────────

@router.post("/storage/cleanup-stale-files")
async def cleanup_stale_files(
    dry_run: bool = True,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
) -> dict:
    """Remove files on disk that have no corresponding Document DB record.

    Always runs as a dry-run by default (dry_run=true) — pass dry_run=false
    to actually delete.  Only touches the uploads directory; never removes
    files that are referenced by any Document row.

    The key fix vs the original broken script: DB paths are stored relative to
    the application working directory (e.g. ``uploads/4/abc.docx``).  We
    resolve them to absolute paths before comparing so the check is correct
    regardless of how pathlib formats the disk paths.
    """
    from app.core.config import get_settings
    settings = get_settings()

    upload_base = Path(settings.upload_dir).resolve()
    if not upload_base.exists():
        return {"stale_files": [], "deleted": 0, "dry_run": dry_run}

    # Build a set of RESOLVED absolute paths that are referenced in the DB
    result = await db.execute(select(Document.file_path))
    db_paths: set[Path] = {
        Path(row[0]).resolve() for row in result.fetchall()
    }

    stale: list[str] = []
    for f in upload_base.rglob("*"):
        if not f.is_file():
            continue
        if f.resolve() not in db_paths:
            stale.append(str(f))

    deleted = 0
    errors: list[str] = []
    if not dry_run:
        for filepath in stale:
            try:
                Path(filepath).unlink()
                deleted += 1
            except Exception as exc:
                errors.append(f"{filepath}: {exc}")

    return {
        "dry_run": dry_run,
        "stale_files": stale,
        "stale_count": len(stale),
        "deleted": deleted,
        "errors": errors,
    }

FAMILY_NAMES = {
    "AC": "Access Control",
    "AU": "Audit & Accountability",
    "CM": "Configuration Management",
    "CP": "Contingency Planning",
    "IA": "Identification & Authentication",
    "IR": "Incident Response",
    "PS": "Personnel Security",
    "SC": "System & Communications Protection",
    "SI": "System & Information Integrity",
    "SA": "System & Services Acquisition",
    "RA": "Risk Assessment",
    "MA": "Maintenance",
    "MP": "Media Protection",
    "PE": "Physical & Environmental Protection",
    "PL": "Planning",
    "PM": "Program Management",
}

STATUS_MAP = {
    "implemented": "pass",
    "inherited": "pass",
    "not_applicable": "pass",
    "partially_implemented": "warn",
    "not_implemented": "fail",
    "planned": "warn",
}

# NIST control → linked infra component / metric
CONTROL_LINKS = {
    "failed_logins": "AC-7",
    "locked_accounts": "AC-2",
    "mfa_adoption": "IA-5",
    "active_users": "AU-12",
    "postgres": "AU-12",
    "redis": "SC-23",
    "nginx": "SC-7",
}


def _serialize_control(c: InternalControlStatus) -> dict:
    try:
        components = json.loads(c.notes) if c.notes else []
    except Exception:
        components = []
    return {
        "id": c.control_id,
        "family": c.control_family,
        "family_name": FAMILY_NAMES.get(c.control_family, c.control_family),
        "title": c.control_title,
        "status": c.status,
        "bucket": STATUS_MAP.get(c.status, "warn"),
        "description": c.evidence_text,
        "components": components,
        "last_checked": c.last_checked.isoformat() if c.last_checked else None,
        "notes": None,  # don't expose raw notes JSON
    }


async def _check_postgres(db: AsyncSession) -> dict:
    try:
        t0 = time.monotonic()
        row = await db.execute(
            text("SELECT pg_database_size(current_database()) AS size_bytes, version() AS ver, "
                 "(SELECT count(*) FROM pg_stat_activity) AS conn_count")
        )
        result = row.fetchone()
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        size_mb = round((result.size_bytes or 0) / 1024 / 1024, 1)
        ver_parts = (result.ver or "").split()
        ver = f"{ver_parts[0]} {ver_parts[1]}" if len(ver_parts) >= 2 else "unknown"
        conns = result.conn_count or 0
        return {
            "status": "healthy",
            "detail": f"{ver} · {conns}/100 conns · {size_mb} MB",
            "latency_ms": latency_ms,
            "nist_control": CONTROL_LINKS["postgres"],
        }
    except Exception as exc:
        return {"status": "degraded", "detail": str(exc)[:120], "latency_ms": None, "nist_control": CONTROL_LINKS["postgres"]}


async def _check_redis() -> dict:
    from app.core.config import get_settings
    settings = get_settings()
    try:
        import redis.asyncio as aioredis
        t0 = time.monotonic()
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        pong = await r.ping()
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        await r.aclose()
        if pong:
            return {
                "status": "healthy",
                "detail": f"Authenticated and responding to PING · {latency_ms} ms latency",
                "latency_ms": latency_ms,
                "nist_control": CONTROL_LINKS["redis"],
            }
        return {"status": "degraded", "detail": "No PONG", "latency_ms": latency_ms, "nist_control": CONTROL_LINKS["redis"]}
    except Exception as exc:
        return {"status": "degraded", "detail": str(exc)[:120], "latency_ms": None, "nist_control": CONTROL_LINKS["redis"]}


async def _check_nginx() -> dict:
    try:
        t0 = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}:%{num_headers}",
            "--max-time", "2", "http://frontend:80/",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        raw = (stdout or b"").decode().strip()
        parts = raw.split(":")
        code = parts[0]
        headers = parts[1] if len(parts) > 1 else "?"
        if code in ("200", "301", "302"):
            return {
                "status": "healthy",
                "detail": f"HTTP {code} · {headers} headers · {latency_ms} ms response",
                "latency_ms": latency_ms,
                "nist_control": CONTROL_LINKS["nginx"],
            }
        return {"status": "degraded", "detail": f"HTTP {code}", "latency_ms": latency_ms, "nist_control": CONTROL_LINKS["nginx"]}
    except Exception:
        return {"status": "unknown", "detail": "Unreachable from backend", "latency_ms": None, "nist_control": CONTROL_LINKS["nginx"]}


@router.get("/metrics")
async def get_admin_metrics(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
) -> dict:
    now = datetime.now(UTC)
    since_24h = now - timedelta(hours=24)

    # ── Failed logins last 24 h ──────────────────────────────────────────────
    failed_logins = await db.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.timestamp >= since_24h,
            AuditLog.action.like("%login%"),
            AuditLog.status_code.in_([401, 423]),
        )
    )

    # ── Locked accounts ──────────────────────────────────────────────────────
    locked_accounts = await db.scalar(
        select(func.count(User.id)).where(
            User.locked_until > now,
            User.locked_until.is_not(None),
        )
    )

    # ── Active users last 24 h ───────────────────────────────────────────────
    active_24h = await db.scalar(
        select(func.count(func.distinct(AuditLog.user_id))).where(
            AuditLog.timestamp >= since_24h,
            AuditLog.user_id.is_not(None),
        )
    )

    # ── MFA adoption ─────────────────────────────────────────────────────────
    total_active_users = await db.scalar(
        select(func.count(User.id)).where(User.is_active == True)
    )
    mfa_enabled_count = await db.scalar(
        select(func.count(User.id)).where(User.is_active == True, User.mfa_enabled == True)
    )
    mfa_pct = round((mfa_enabled_count or 0) / max(total_active_users or 1, 1) * 100)

    # ── Unresolved security events by severity ───────────────────────────────
    events_result = await db.execute(
        select(SecurityEvent.severity, func.count(SecurityEvent.id))
        .where(SecurityEvent.resolved == False)
        .group_by(SecurityEvent.severity)
    )
    events_by_severity = {row[0]: row[1] for row in events_result}

    # ── NIST controls ─────────────────────────────────────────────────────────
    ctrl_result = await db.execute(
        select(InternalControlStatus).order_by(InternalControlStatus.control_id)
    )
    controls = ctrl_result.scalars().all()

    ctrl_counts = {"pass": 0, "warn": 0, "fail": 0}
    families: dict[str, dict] = {}
    failing_controls = []

    for c in controls:
        bucket = STATUS_MAP.get(c.status, "warn")
        ctrl_counts[bucket] += 1
        fam = c.control_family or c.control_id.split("-")[0]
        if fam not in families:
            families[fam] = {
                "name": FAMILY_NAMES.get(fam, fam),
                "pass": 0, "warn": 0, "fail": 0,
                "controls": [],
            }
        families[fam][bucket] += 1
        serialized = _serialize_control(c)
        families[fam]["controls"].append(serialized)
        if bucket == "fail":
            failing_controls.append(serialized)

    # ── Recent security alerts (last 10 unresolved) ──────────────────────────
    alerts_result = await db.execute(
        select(SecurityEvent)
        .where(SecurityEvent.resolved == False)
        .order_by(SecurityEvent.timestamp.desc())
        .limit(10)
    )
    alerts = [
        {
            "id": e.id,
            "type": e.event_type,
            "severity": e.severity,
            "description": e.description,
            "created_at": e.timestamp.isoformat(),
        }
        for e in alerts_result.scalars()
    ]

    # ── Infrastructure health ────────────────────────────────────────────────
    postgres_health, redis_health, nginx_health = await asyncio.gather(
        _check_postgres(db),
        _check_redis(),
        _check_nginx(),
    )

    return {
        "generated_at": now.isoformat(),
        "metrics": {
            "failed_logins_24h": failed_logins or 0,
            "locked_accounts": locked_accounts or 0,
            "active_users_24h": active_24h or 0,
            "total_active_users": total_active_users or 0,
            "mfa_enabled": mfa_enabled_count or 0,
            "mfa_adoption_pct": mfa_pct,
            "control_links": CONTROL_LINKS,
        },
        "security_events": {
            "by_severity": events_by_severity,
            "total_unresolved": sum(events_by_severity.values()),
            "recent": alerts,
        },
        "controls": {
            "summary": ctrl_counts,
            "total": len(controls),
            "failing": failing_controls,
            "families": families,
        },
        "infrastructure": {
            "postgres": postgres_health,
            "redis": redis_health,
            "nginx": nginx_health,
        },
    }


@router.get("/controls/{control_id}")
async def get_control_detail(
    control_id: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
) -> dict:
    result = await db.execute(
        select(InternalControlStatus).where(
            InternalControlStatus.control_id == control_id.upper()
        )
    )
    c = result.scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail=f"Control {control_id} not found")

    # Pull recent audit log entries related to this control's family
    fam = c.control_family or control_id.split("-")[0]
    recent_events_result = await db.execute(
        select(SecurityEvent)
        .order_by(SecurityEvent.timestamp.desc())
        .limit(5)
    )
    recent_events = [
        {
            "id": e.id,
            "type": e.event_type,
            "severity": e.severity,
            "description": e.description,
            "timestamp": e.timestamp.isoformat(),
            "resolved": e.resolved,
        }
        for e in recent_events_result.scalars()
    ]

    return {
        **_serialize_control(c),
        "recent_events": recent_events,
    }


@router.post("/controls/{control_id}/status")
async def update_control_status(
    control_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> dict:
    result = await db.execute(
        select(InternalControlStatus).where(
            InternalControlStatus.control_id == control_id.upper()
        )
    )
    c = result.scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail=f"Control {control_id} not found")

    allowed = {"implemented", "partially_implemented", "not_implemented", "inherited", "not_applicable", "planned"}
    new_status = body.get("status", "").lower()
    if new_status not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(sorted(allowed))}")

    c.status = new_status
    c.last_checked = datetime.now(UTC)
    c.updated_by = current_user.get("id")
    if body.get("notes"):
        c.notes = body["notes"]
    await db.commit()
    return _serialize_control(c)


# ── Stat card drill-down data endpoints ──────────────────────────────────────

@router.get("/data/failed-logins")
async def get_failed_logins(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
) -> dict:
    since_24h = datetime.now(UTC) - timedelta(hours=24)
    result = await db.execute(
        select(AuditLog, User)
        .outerjoin(User, AuditLog.user_id == User.id)
        .where(
            AuditLog.timestamp >= since_24h,
            AuditLog.action.like("%login%"),
            AuditLog.status_code.in_([401, 423]),
        )
        .order_by(AuditLog.timestamp.desc())
        .limit(100)
    )
    rows = result.all()
    return {
        "title": "Failed Logins (Last 24h)",
        "columns": ["Timestamp", "Username", "IP Address", "Status", "Action"],
        "rows": [
            {
                "timestamp": log.timestamp.isoformat(),
                "username": user.username if user else f"user_id:{log.user_id}" if log.user_id else "unknown",
                "ip_address": log.ip_address or "—",
                "status_code": log.status_code,
                "action": log.action,
            }
            for log, user in rows
        ],
    }


@router.get("/data/locked-accounts")
async def get_locked_accounts(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
) -> dict:
    now = datetime.now(UTC)
    result = await db.execute(
        select(User)
        .where(User.locked_until > now, User.locked_until.is_not(None))
        .order_by(User.locked_until.desc())
    )
    users = result.scalars().all()
    return {
        "title": "Currently Locked Accounts",
        "columns": ["Username", "Email", "Role", "Locked Until", "Failed Attempts"],
        "rows": [
            {
                "username": u.username,
                "email": u.email,
                "role": u.role,
                "locked_until": u.locked_until.isoformat() if u.locked_until else None,
                "failed_logins": u.failed_logins,
            }
            for u in users
        ],
    }


@router.get("/data/mfa-status")
async def get_mfa_status(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
) -> dict:
    result = await db.execute(
        select(User)
        .where(User.is_active == True)
        .order_by(User.mfa_enabled.desc(), User.username)
    )
    users = result.scalars().all()
    return {
        "title": "MFA Adoption — All Active Users",
        "columns": ["Username", "Email", "Role", "MFA Enabled", "Last Login"],
        "rows": [
            {
                "username": u.username,
                "email": u.email,
                "role": u.role,
                "mfa_enabled": u.mfa_enabled,
                "last_login": u.last_login.isoformat() if u.last_login else None,
            }
            for u in users
        ],
    }


@router.get("/data/active-users")
async def get_active_users(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
) -> dict:
    since_24h = datetime.now(UTC) - timedelta(hours=24)
    # Get distinct user_ids active in last 24h with their most recent action
    result = await db.execute(
        select(
            AuditLog.user_id,
            User.username,
            User.email,
            User.role,
            func.max(AuditLog.timestamp).label("last_seen"),
            func.count(AuditLog.id).label("action_count"),
        )
        .outerjoin(User, AuditLog.user_id == User.id)
        .where(AuditLog.timestamp >= since_24h, AuditLog.user_id.is_not(None))
        .group_by(AuditLog.user_id, User.username, User.email, User.role)
        .order_by(func.max(AuditLog.timestamp).desc())
    )
    rows = result.all()
    return {
        "title": "Active Users (Last 24h)",
        "columns": ["Username", "Email", "Role", "Last Seen", "Actions"],
        "rows": [
            {
                "username": row.username or f"user_id:{row.user_id}",
                "email": row.email or "—",
                "role": row.role or "—",
                "last_seen": row.last_seen.isoformat(),
                "action_count": row.action_count,
            }
            for row in rows
        ],
    }
