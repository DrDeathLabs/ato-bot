"""User management — admin only."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import get_current_user, require_admin, require_assessor
from app.core.security import hash_password
from app.models.orm import RefreshToken, User
from app.models.schemas import UserCreate, UserPasswordReset, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
) -> list[UserResponse]:
    result = await db.execute(select(User).order_by(User.created_at))
    return result.scalars().all()


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
) -> UserResponse:
    # Check uniqueness
    result = await db.execute(
        select(User).where((User.username == body.username) | (User.email == body.email))
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username or email already exists")

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/me", response_model=UserResponse)
async def get_me(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> UserResponse:
    """Any authenticated user can fetch their own profile."""
    result = await db.execute(select(User).where(User.id == current_user["id"]))
    return result.scalar_one()


@router.get("/system-owners", response_model=list[UserResponse])
async def list_system_owners(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> list[UserResponse]:
    """Return active FISMA system-owner accounts for project assignment."""
    result = await db.execute(
        select(User)
        .where(User.role == "system_owner", User.is_active.is_(True))
        .order_by(User.username)
    )
    return result.scalars().all()


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> UserResponse:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
) -> UserResponse:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if body.email is not None:
        user.email = body.email
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/{user_id}/reset-password", response_model=UserResponse)
async def reset_user_password(
    user_id: int,
    body: UserPasswordReset,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
) -> UserResponse:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = hash_password(body.password)
    user.failed_logins = 0
    user.locked_until = None

    tokens_result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked == False,  # noqa: E712
        )
    )
    for token in tokens_result.scalars().all():
        token.revoked = True

    await db.commit()
    await db.refresh(user)
    return user
