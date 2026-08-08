from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import Role, get_current_user
from app.models.orm import Assessment, ControlFinding, Project
from app.services.assistant_service import (
    CONTROL_ASSISTANT_SYSTEM_PROMPT,
    GENERAL_ASSISTANT_SYSTEM_PROMPT,
    REMEDIATION_ASSISTANT_SYSTEM_PROMPT,
    add_attachment,
    add_uploaded_file_attachment,
    append_message,
    build_context_block,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_attachments,
    list_conversations_for_user,
    list_messages,
    resolve_assistant_route,
    serialize_attachment,
    serialize_conversation,
    serialize_conversation_summary,
    serialize_message,
    update_conversation_title,
)
from app.services.llm.runtime import build_provider_for_purpose
from app.services.prompt_manager import get_prompt

router = APIRouter(prefix="/assistant", tags=["assistant"])
ALLOWED_THINKING_EFFORTS = {"low", "medium", "high"}


class AttachmentInput(BaseModel):
    attachment_type: str = Field(alias="type")
    resource_id: str = ""
    label: str | None = None
    context_json: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


class CreateConversationRequest(BaseModel):
    mode: str = "general"
    title: str | None = None
    project_id: int | None = None
    assessment_id: int | None = None
    attachments: list[AttachmentInput] = Field(default_factory=list)
    thinking_effort: str | None = None


class MessageRequest(BaseModel):
    content: str
    hidden: bool = False
    thinking_effort: str | None = None


class AddAttachmentRequest(BaseModel):
    attachment_type: str = Field(alias="type")
    resource_id: str = ""
    context_json: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


class UpdateConversationRequest(BaseModel):
    title: str


def _default_prompt_for(prompt_id: str) -> str:
    if prompt_id == "assistant_control":
        return CONTROL_ASSISTANT_SYSTEM_PROMPT
    if prompt_id == "assistant_remediation":
        return REMEDIATION_ASSISTANT_SYSTEM_PROMPT
    if prompt_id == "assistant_workspace":
        return GENERAL_ASSISTANT_SYSTEM_PROMPT
    if prompt_id == "assistant_evidence":
        return CONTROL_ASSISTANT_SYSTEM_PROMPT
    if prompt_id == "assistant_admin_explainer":
        return GENERAL_ASSISTANT_SYSTEM_PROMPT
    return GENERAL_ASSISTANT_SYSTEM_PROMPT


async def _validate_scope_access(
    db: AsyncSession,
    current_user: dict,
    *,
    project_id: int | None,
    assessment_id: int | None,
) -> None:
    owner_id = None
    if assessment_id:
        result = await db.execute(
            select(Project.owner_id)
            .join(Assessment, Assessment.project_id == Project.id)
            .where(Assessment.id == assessment_id)
        )
        owner_id = result.scalar_one_or_none()
        if owner_id is None:
            raise HTTPException(status_code=404, detail="Assessment not found")
    elif project_id:
        result = await db.execute(select(Project.owner_id).where(Project.id == project_id))
        owner_id = result.scalar_one_or_none()
        if owner_id is None:
            raise HTTPException(status_code=404, detail="Project not found")

    if current_user["role"] == Role.SYSTEM_OWNER and owner_id is not None and owner_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")


async def _conversation_payload(db: AsyncSession, conversation_id: int) -> dict[str, Any]:
    convo = await get_conversation(db, conversation_id)
    attachments = await list_attachments(db, conversation_id)
    messages = await list_messages(db, conversation_id)
    return {
        "conversation": serialize_conversation(convo),
        "attachments": [serialize_attachment(a) for a in attachments],
        "messages": [serialize_message(m) for m in messages],
    }


@router.post("/conversations")
async def create_assistant_conversation(
    body: CreateConversationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    await _validate_scope_access(
        db,
        current_user,
        project_id=body.project_id,
        assessment_id=body.assessment_id,
    )
    convo = await create_conversation(
        db,
        user_id=current_user["id"],
        mode=body.mode,
        title=body.title,
        project_id=body.project_id,
        assessment_id=body.assessment_id,
        attachments=[item.model_dump(by_alias=False) for item in body.attachments],
    )
    return await _conversation_payload(db, convo.id)


@router.get("/conversations")
async def list_assistant_conversations(
    project_id: int | None = None,
    assessment_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    conversations = await list_conversations_for_user(
        db,
        user_id=current_user["id"],
        project_id=project_id,
        assessment_id=assessment_id,
    )
    items = [await serialize_conversation_summary(db, convo) for convo in conversations]
    return {"items": items}


@router.get("/conversations/{conversation_id}")
async def get_assistant_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    convo = await get_conversation(db, conversation_id)
    await _validate_scope_access(
        db,
        current_user,
        project_id=convo.project_id,
        assessment_id=convo.assessment_id,
    )
    return await _conversation_payload(db, conversation_id)


@router.patch("/conversations/{conversation_id}")
async def update_assistant_conversation(
    conversation_id: int,
    body: UpdateConversationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    convo = await get_conversation(db, conversation_id)
    if convo.created_by != current_user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="Title is required")
    updated = await update_conversation_title(
        db,
        conversation_id=conversation_id,
        title=body.title,
    )
    return {"conversation": serialize_conversation(updated)}


@router.delete("/conversations/{conversation_id}")
async def delete_assistant_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict[str, bool]:
    convo = await get_conversation(db, conversation_id)
    if convo.created_by != current_user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    await delete_conversation(db, conversation_id=conversation_id)
    return {"ok": True}


@router.post("/conversations/{conversation_id}/attachments")
async def add_assistant_attachment(
    conversation_id: int,
    body: AddAttachmentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    convo = await get_conversation(db, conversation_id)
    await _validate_scope_access(
        db,
        current_user,
        project_id=convo.project_id,
        assessment_id=convo.assessment_id,
    )
    attachment = await add_attachment(
        db,
        conversation_id=conversation_id,
        attachment_type=body.attachment_type,
        resource_id=body.resource_id,
        context_json=body.context_json,
    )
    return {"attachment": serialize_attachment(attachment)}


@router.post("/conversations/{conversation_id}/files")
async def upload_assistant_files(
    conversation_id: int,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    convo = await get_conversation(db, conversation_id)
    await _validate_scope_access(
        db,
        current_user,
        project_id=convo.project_id,
        assessment_id=convo.assessment_id,
    )

    created = []
    for upload in files:
        content = await upload.read()
        attachment = await add_uploaded_file_attachment(
            db,
            conversation_id=conversation_id,
            filename=upload.filename or "attachment",
            content=content,
            content_type=upload.content_type,
        )
        created.append(serialize_attachment(attachment))

    return {"attachments": created}


@router.post("/conversations/{conversation_id}/messages")
async def send_assistant_message(
    conversation_id: int,
    body: MessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    convo = await get_conversation(db, conversation_id)
    await _validate_scope_access(
        db,
        current_user,
        project_id=convo.project_id,
        assessment_id=convo.assessment_id,
    )
    attachments = await list_attachments(db, conversation_id)
    prompt_id, runtime_purpose = resolve_assistant_route(convo.mode, attachments)
    system_prompt = await get_prompt(prompt_id, _default_prompt_for(prompt_id))
    await append_message(
        db,
        conversation_id=conversation_id,
        role="user",
        content=body.content,
        metadata_json={"hidden": body.hidden},
    )
    messages = await list_messages(db, conversation_id)
    context_block = await build_context_block(db, conversation_id)
    history_lines = []
    for msg in messages[-18:]:
        role = "User" if msg.role == "user" else "Assistant"
        history_lines.append(f"{role}: {msg.content}")
    prompt = (
        f"Attached app context:\n{context_block}\n\n"
        f"Conversation so far:\n" + ("\n".join(history_lines) if history_lines else "None yet.") +
        "\n\nRespond to the user's latest message. Keep the response grounded in the attached context when present."
    )

    requested_effort = (body.thinking_effort or "").strip().lower() or None
    if requested_effort and requested_effort not in ALLOWED_THINKING_EFFORTS:
        raise HTTPException(status_code=400, detail="Invalid thinking_effort")

    try:
        provider, runtime = await build_provider_for_purpose(
            db,
            runtime_purpose,
            reasoning_effort=requested_effort,
        )
        text = (await provider.complete(system_prompt, prompt)).strip()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Assistant response failed: {exc}")

    await append_message(
        db,
        conversation_id=conversation_id,
        role="assistant",
        content=text,
        metadata_json={"runtime_purpose": runtime.purpose, "model": runtime.model},
    )
    await db.commit()
    payload = await _conversation_payload(db, conversation_id)
    payload["runtime"] = {
        "purpose": runtime.purpose,
        "provider": runtime.provider,
        "model": runtime.model,
        "reasoning_effort": runtime.reasoning_effort,
    }
    return payload


@router.get("/suggestions")
async def assistant_suggestions(
    mode: str = "general",
    _: dict = Depends(get_current_user),
) -> dict[str, list[str]]:
    suggestions = {
        "general": [
            "Explain this control in plain English.",
            "What would a strong ATO package include for a high baseline system?",
            "What is the difference between 800-53 and 800-53A?",
        ],
        "control": [
            "Why was this control marked this way?",
            "What evidence would change this result?",
            "Help me draft stronger SSP language for this control.",
        ],
        "remediation": [
            "What should I remediate first?",
            "What package changes would close the biggest gaps?",
            "What documents should I generate next?",
        ],
        "workspace": [
            "What are the biggest risk themes in this assessment?",
            "Which control families need the most work?",
            "Summarize what the evidence is missing.",
        ],
        "admin_runtime": [
            "Explain what this setting or prompt is doing.",
            "Which model route is being used here and why?",
            "What should I tune first for better speed or quality?",
        ],
    }
    return {"suggestions": suggestions.get(mode, suggestions["general"])}
