"""Admin API — manage LLM prompt overrides."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.rbac import require_admin
from app.services.prompt_manager import (
    PROMPT_REGISTRY,
    list_prompts,
    reset_prompt,
    save_prompt,
)

router = APIRouter(prefix="/admin/prompts", tags=["admin-prompts"])


class PromptUpdateRequest(BaseModel):
    content: str


@router.get("")
async def get_all_prompts(current_user: dict = Depends(require_admin)) -> list[dict]:
    """List all prompts with current content (override or default) and metadata."""
    return await list_prompts()


@router.put("/{prompt_id}")
async def update_prompt(
    prompt_id: str,
    body: PromptUpdateRequest,
    current_user: dict = Depends(require_admin),
) -> dict:
    """Save a prompt override."""
    if prompt_id not in PROMPT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown prompt '{prompt_id}'")
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Prompt content cannot be empty")
    await save_prompt(prompt_id, body.content, current_user.get("username", "admin"))
    return {"id": prompt_id, "saved": True}


@router.delete("/{prompt_id}")
async def reset_prompt_to_default(
    prompt_id: str,
    current_user: dict = Depends(require_admin),
) -> dict:
    """Delete override — reverts to hardcoded default."""
    if prompt_id not in PROMPT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown prompt '{prompt_id}'")
    await reset_prompt(prompt_id)
    return {"id": prompt_id, "reset": True}
