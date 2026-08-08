"""System-level assessment policy APIs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_security_officer, require_viewer
from app.models.orm import AssessmentPolicy
from app.services.assessment_policy import (
    activate_policy,
    build_bucket_preview,
    clone_policy_to_draft,
    delete_policy_draft,
    get_active_assessment_policy,
    get_policy_by_id,
    serialize_policy,
    update_policy_bucket,
    update_policy_metadata,
)

router = APIRouter(prefix="/assessment-policy", tags=["assessment-policy"])


class PolicyMetadataPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    notes: str | None = None
    default_thresholds: dict | None = None


class PolicyBucketPatch(BaseModel):
    label: str | None = None
    description: str | None = None
    sort_order: int | None = None
    objective_weight: float | None = None
    critical_by_default: bool | None = None
    minimum_evidence_strength: float | None = None
    negative_evidence_penalty: float | None = None
    contradiction_penalty: float | None = None
    future_state_cap: float | None = None
    inheritance_allowed: bool | None = None
    compensating_allowed: bool | None = None
    confidence_cap_if_only_weak_evidence: float | None = None
    confidence_cap_if_compensating_only: float | None = None
    active: bool | None = None


@router.get("/active")
async def get_active_policy(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> dict:
    policy = await get_active_assessment_policy(db)
    if policy is None:
        raise HTTPException(status_code=404, detail="No active assessment policy configured")
    await db.refresh(policy, attribute_names=["buckets"])
    return serialize_policy(policy)


@router.get("")
async def list_policies(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> list[dict]:
    rows = (
        await db.execute(
            select(AssessmentPolicy)
            .order_by(
                AssessmentPolicy.status.asc(),
                AssessmentPolicy.effective_at.desc().nullslast(),
                AssessmentPolicy.id.desc(),
            )
        )
    ).scalars().all()
    return [serialize_policy(row, include_buckets=False) for row in rows]


@router.get("/{policy_id}")
async def get_policy(
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> dict:
    policy = await get_policy_by_id(db, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Assessment policy not found")
    return serialize_policy(policy)


@router.patch("/{policy_id}")
async def patch_policy(
    policy_id: int,
    body: PolicyMetadataPatch,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_security_officer),
) -> dict:
    policy = await get_policy_by_id(db, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Assessment policy not found")
    try:
        policy = await update_policy_metadata(
            db,
            policy,
            name=body.name,
            description=body.description,
            notes=body.notes,
            default_thresholds=body.default_thresholds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return serialize_policy(policy)


@router.patch("/{policy_id}/buckets/{bucket_key}")
async def patch_policy_bucket(
    policy_id: int,
    bucket_key: str,
    body: PolicyBucketPatch,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_security_officer),
) -> dict:
    policy = await get_policy_by_id(db, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Assessment policy not found")
    try:
        bucket = await update_policy_bucket(db, policy, bucket_key, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "policy": serialize_policy(policy),
        "updated_bucket": bucket.bucket_key,
    }


@router.post("/{policy_id}/clone")
async def clone_policy(
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_security_officer),
) -> dict:
    policy = await get_policy_by_id(db, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Assessment policy not found")
    draft = await clone_policy_to_draft(db, policy, created_by=current_user["id"])
    return serialize_policy(draft)


@router.post("/{policy_id}/activate")
async def activate_policy_route(
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_security_officer),
) -> dict:
    policy = await get_policy_by_id(db, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Assessment policy not found")
    try:
        policy = await activate_policy(db, policy)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return serialize_policy(policy)


@router.delete("/{policy_id}")
async def delete_policy(
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_security_officer),
) -> dict:
    policy = await get_policy_by_id(db, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Assessment policy not found")
    try:
        await delete_policy_draft(db, policy)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"deleted": True, "policy_id": policy_id}


@router.get("/{policy_id}/preview")
async def preview_policy(
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> dict:
    policy = await get_policy_by_id(db, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Assessment policy not found")
    compare_to = None
    if policy.status == "draft":
        compare_to = await get_active_assessment_policy(db)
        if compare_to is not None and compare_to.id == policy.id:
            compare_to = None
        elif compare_to is not None:
            await db.refresh(compare_to, attribute_names=["buckets"])
    return build_bucket_preview(policy, compare_to=compare_to)
