"""Audit logging middleware — logs every request to the audit_logs table."""
import json
import time
from typing import Callable

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.security import TokenValidationError, decode_token

settings = get_settings()

# Endpoints that do not need to be logged (health, static, docs)
_SKIP_PATHS = {"/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico"}


def _extract_user_id(request: Request) -> int | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        payload = decode_token(auth.removeprefix("Bearer "))
        return int(payload.get("sub", 0)) or None
    except (TokenValidationError, ValueError):
        return None


def _derive_action(method: str, path: str) -> str:
    """Best-effort human-readable action label."""
    segments = [s for s in path.split("/") if s]
    resource = segments[-1] if segments else "unknown"
    return f"{method}:{resource}"


def _derive_resource(path: str) -> tuple[str | None, str | None]:
    """Extract resource_type and resource_id from path like /api/projects/42."""
    parts = [s for s in path.split("/") if s]
    resource_type = None
    resource_id = None
    for i, part in enumerate(parts):
        if part not in ("api", "v1", "v2") and not part.isdigit():
            resource_type = part
            if i + 1 < len(parts) and parts[i + 1].isdigit():
                resource_id = parts[i + 1]
            break
    return resource_type, resource_id


async def audit_middleware(request: Request, call_next: Callable) -> Response:
    if request.url.path in _SKIP_PATHS:
        return await call_next(request)

    start = time.monotonic()
    response = await call_next(request)
    duration_ms = int((time.monotonic() - start) * 1000)

    user_id = _extract_user_id(request)
    resource_type, resource_id = _derive_resource(request.url.path)
    action = _derive_action(request.method, request.url.path)
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()

    try:
        async with AsyncSessionLocal() as db:
            from app.models.orm import AuditLog
            log = AuditLog(
                user_id=user_id,
                ip_address=ip,
                user_agent=request.headers.get("User-Agent", "")[:512],
                method=request.method,
                endpoint=str(request.url.path)[:512],
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                status_code=response.status_code,
            )
            db.add(log)
            await db.commit()
    except Exception:
        pass  # Never let audit failures break the request

    return response
