"""Authentication endpoints — login, logout, token refresh, MFA setup."""
import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.rbac import get_current_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_totp_secret,
    get_totp_uri,
    hash_password,
    verify_password,
    verify_totp,
)
from app.models.orm import RefreshToken, SecurityEvent, User
from app.models.schemas import (
    LoginRequest,
    MFASetupResponse,
    MFAVerifyRequest,
    RefreshRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _emit_security_event(
    db: AsyncSession,
    event_type: str,
    severity: str,
    description: str,
    user_id: int | None,
    source_ip: str | None,
) -> None:
    event = SecurityEvent(
        event_type=event_type,
        severity=severity,
        description=description,
        user_id=user_id,
        source_ip=source_ip,
    )
    db.add(event)


async def _prune_refresh_tokens(db: AsyncSession, *, user_id: int | None = None) -> None:
    now = datetime.now(UTC)
    query = select(RefreshToken)
    if user_id is not None:
        query = query.where(RefreshToken.user_id == user_id)
    tokens = (await db.execute(query)).scalars().all()

    for token in tokens:
        if not token.revoked and token.expires_at and token.expires_at < now:
            token.revoked = True

    active_tokens = [
        token
        for token in tokens
        if not token.revoked and token.expires_at and token.expires_at >= now
    ]
    stale_cutoff = now - timedelta(days=settings.stale_refresh_session_days)
    for token in active_tokens:
        if token.created_at and token.created_at <= stale_cutoff:
            token.revoked = True

    active_tokens = [
        token
        for token in tokens
        if not token.revoked and token.expires_at and token.expires_at >= now
    ]
    active_tokens.sort(key=lambda token: token.created_at or now, reverse=True)

    max_sessions = max(int(settings.max_active_refresh_sessions_per_user or 1), 1)
    for token in active_tokens[max_sessions:]:
        token.revoked = True


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()

    login_identifier = (body.username or "").strip()
    result = await db.execute(
        select(User).where(
            or_(
                User.username == login_identifier,
                User.email == login_identifier,
            )
        )
    )
    user: User | None = result.scalar_one_or_none()

    # Account does not exist — still return generic error (AU-9, IA-6)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Check lockout
    if user.locked_until and user.locked_until > datetime.now(UTC):
        await _emit_security_event(db, "account_locked_attempt", "high",
            f"Login attempt on locked account: {user.username}", user.id, ip)
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account temporarily locked")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account disabled")

    if not verify_password(body.password, user.hashed_password):
        user.failed_logins += 1
        if user.failed_logins >= settings.max_login_attempts:
            user.locked_until = datetime.now(UTC) + timedelta(minutes=settings.lockout_minutes)
            await _emit_security_event(db, "account_locked", "high",
                f"Account locked after {user.failed_logins} failed attempts: {user.username}", user.id, ip)
        else:
            await _emit_security_event(db, "failed_login", "medium",
                f"Failed login attempt for {user.username} ({user.failed_logins}/{settings.max_login_attempts})",
                user.id, ip)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # MFA check
    if user.mfa_enabled:
        if not body.totp_code:
            return TokenResponse(access_token="", refresh_token="", mfa_required=True)
        if not verify_totp(user.mfa_secret, body.totp_code):
            await _emit_security_event(db, "mfa_bypass_attempt", "high",
                f"Invalid MFA code for {user.username}", user.id, ip)
            await db.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA code")

    # Successful login
    user.failed_logins = 0
    user.locked_until = None
    user.last_login = datetime.now(UTC)
    await _prune_refresh_tokens(db, user_id=user.id)

    access_token = create_access_token(str(user.id), user.role)
    refresh_token = create_refresh_token(str(user.id))

    rt = RefreshToken(
        user_id=user.id,
        token_hash=_hash_token(refresh_token),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(rt)
    await _prune_refresh_tokens(db, user_id=user.id)
    await db.commit()

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
async def refresh_tokens(
    request: Request,
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    token_hash = _hash_token(body.refresh_token)
    await _prune_refresh_tokens(db, user_id=user_id)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False,
        )
    )
    stored = result.scalar_one_or_none()
    if stored is None or stored.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired or revoked")

    # Rotate — revoke old, issue new
    stored.revoked = True

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    access_token = create_access_token(str(user.id), user.role)
    new_refresh = create_refresh_token(str(user.id))
    rt = RefreshToken(
        user_id=user.id,
        token_hash=_hash_token(new_refresh),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(rt)
    await _prune_refresh_tokens(db, user_id=user.id)
    await db.commit()

    return TokenResponse(access_token=access_token, refresh_token=new_refresh)


@router.post("/logout")
async def logout(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    token_hash = _hash_token(body.refresh_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    stored = result.scalar_one_or_none()
    if stored:
        stored.revoked = True
        await _prune_refresh_tokens(db, user_id=stored.user_id)
        await db.commit()
    return {"detail": "Logged out"}


@router.post("/mfa/setup", response_model=MFASetupResponse)
async def setup_mfa(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MFASetupResponse:
    result = await db.execute(select(User).where(User.id == current_user["id"]))
    user = result.scalar_one()
    secret = generate_totp_secret()
    user.mfa_secret = secret
    await db.commit()
    return MFASetupResponse(
        secret=secret,
        provisioning_uri=get_totp_uri(secret, user.username),
    )


@router.post("/mfa/verify")
async def verify_mfa(
    body: MFAVerifyRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(User).where(User.id == current_user["id"]))
    user = result.scalar_one()
    if not user.mfa_secret:
        raise HTTPException(status_code=400, detail="MFA not set up")
    if not verify_totp(user.mfa_secret, body.totp_code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    user.mfa_enabled = True
    await db.commit()
    return {"detail": "MFA enabled"}


@router.post("/mfa/disable")
async def disable_mfa(
    body: MFAVerifyRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(User).where(User.id == current_user["id"]))
    user = result.scalar_one()
    if not user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA not enabled")
    if not verify_totp(user.mfa_secret, body.totp_code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    user.mfa_enabled = False
    user.mfa_secret = None
    await db.commit()
    return {"detail": "MFA disabled"}
