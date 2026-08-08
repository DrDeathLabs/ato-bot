from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.orm import (
    Assessment,
    AssistantContextAttachment,
    AssistantConversation,
    AssistantMessage,
    CommonControlProvider,
    ControlFinding,
    Document,
    PolicyLibrary,
    Project,
    ProcedureLibrary,
    RemediationReport,
)
from app.services.parsers.dispatcher import parse_document
from app.services.llm.runtime import build_provider_for_purpose

settings = get_settings()
ASSISTANT_UPLOAD_DIR = Path(settings.upload_dir) / "assistant_context"
MAX_ASSISTANT_CONTEXT_CHARS = 12000
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".tiff", ".bmp"}
VISION_ATTACHMENT_SYSTEM_PROMPT = """You are helping derive grounded assistant context from an uploaded screenshot or image.

Your job is to describe what is visible in the image in a way that is useful for later cybersecurity, compliance, RMF, and evidence discussions.

Rules:
- Focus on observable content only.
- Extract visible text, labels, settings, messages, tables, charts, or UI elements when present.
- If the image appears to be a policy, SSP, scan result, configuration screen, diagram, or evidence artifact, say that.
- Do not speculate beyond what can reasonably be seen.
- Keep the output concise but specific.
"""

GENERAL_ASSISTANT_SYSTEM_PROMPT = """You are the ATO Bot Cyber Workspace Assistant.

You help users understand cybersecurity, NIST SP 800-53 Rev 5, 800-53A assessment criteria, RMF, compliance evidence, remediation planning, and how this app is behaving.

Behavior rules:
- Stay grounded in cybersecurity, compliance, evidence, assessment, remediation, and ATO preparation.
- If project-specific context is attached, use it and say when you are relying on that context.
- If you are giving general domain guidance instead of app-grounded facts, say so clearly.
- Do not invent evidence, documents, or assessment outcomes.
- When asked what would change a result, give specific evidence or remediation suggestions.
- Prefer concise, practical guidance over generic boilerplate.
"""

CONTROL_ASSISTANT_SYSTEM_PROMPT = """You are the ATO Bot Control Assistant.

You help the user understand a specific NIST SP 800-53 control, related 800-53A objectives, the current assessment status, supporting evidence, challenge notes, and what would be needed to improve or defend the determination.

Behavior rules:
- Focus on the attached control, finding, and evidence context.
- Explain why the current result was reached in plain English.
- Distinguish between evidence that exists, evidence that is missing, and your own recommendation.
- Suggest concrete remediation steps, evidence additions, SSP language, or assessor-facing rationale when asked.
- Do not claim a control is satisfied unless the attached evidence supports that statement.
"""

REMEDIATION_ASSISTANT_SYSTEM_PROMPT = """You are the ATO Bot Remediation Assistant.

You help the user understand assessment gaps, remediation priorities, artifact packages, SSP language, policy and procedure updates, and what package changes would most likely improve the next assessment run.

Behavior rules:
- Focus on practical remediation planning.
- Prefer consolidated, realistic package improvements over one-off control paperwork.
- Tie recommendations back to the attached findings or remediation context.
- When the user asks what to generate next, prioritize the smallest credible package change with the highest expected compliance impact.
- Distinguish between grounded project facts and your recommendation.
"""


def resolve_assistant_route(mode: str, attachments: list[AssistantContextAttachment]) -> tuple[str, str]:
    attachment_types = {a.attachment_type for a in attachments}
    if mode == "remediation" or "remediation" in attachment_types:
        return "assistant_remediation", "chat_remediation"
    if mode == "control" or {"control", "finding"} & attachment_types:
        return "assistant_control", "chat_control"
    if mode == "workspace":
        return "assistant_workspace", "chat_workspace"
    if mode == "admin_runtime" or "admin_runtime" in attachment_types:
        return "assistant_admin_explainer", "chat_admin_explainer"
    if "evidence" in attachment_types:
        return "assistant_evidence", "chat_evidence"
    return "assistant_general", "chat_general"


async def create_conversation(
    db: AsyncSession,
    *,
    user_id: int,
    mode: str,
    title: str | None,
    project_id: int | None,
    assessment_id: int | None,
    attachments: list[dict[str, Any]] | None,
) -> AssistantConversation:
    convo = AssistantConversation(
        mode=mode,
        title=title or None,
        project_id=project_id,
        assessment_id=assessment_id,
        created_by=user_id,
    )
    db.add(convo)
    await db.flush()
    for raw in attachments or []:
        snap = await build_attachment_snapshot(
            db,
            attachment_type=(raw.get("attachment_type") or raw.get("type") or "general").strip(),
            resource_id=str(raw.get("resource_id") or raw.get("id") or ""),
            context_json=raw.get("context_json") or {},
        )
        db.add(
            AssistantContextAttachment(
                conversation_id=convo.id,
                attachment_type=snap["attachment_type"],
                resource_id=snap["resource_id"],
                label=snap.get("label"),
                context_json=snap.get("context_json"),
            )
        )
    await db.flush()
    if not convo.title:
        convo.title = await suggest_conversation_title(db, convo.id)
    await db.commit()
    return await get_conversation(db, convo.id)


async def get_conversation(db: AsyncSession, conversation_id: int) -> AssistantConversation:
    result = await db.execute(
        select(AssistantConversation).where(AssistantConversation.id == conversation_id)
    )
    convo = result.scalar_one_or_none()
    if convo is None:
        raise ValueError("Conversation not found")
    return convo


async def list_conversations_for_user(
    db: AsyncSession,
    *,
    user_id: int,
    project_id: int | None = None,
    assessment_id: int | None = None,
) -> list[AssistantConversation]:
    stmt = (
        select(AssistantConversation)
        .where(AssistantConversation.created_by == user_id)
        .order_by(AssistantConversation.updated_at.desc(), AssistantConversation.id.desc())
    )
    if project_id is not None:
        stmt = stmt.where(AssistantConversation.project_id == project_id)
    if assessment_id is not None:
        stmt = stmt.where(AssistantConversation.assessment_id == assessment_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_messages(db: AsyncSession, conversation_id: int) -> list[AssistantMessage]:
    result = await db.execute(
        select(AssistantMessage)
        .where(AssistantMessage.conversation_id == conversation_id)
        .order_by(AssistantMessage.created_at.asc(), AssistantMessage.id.asc())
    )
    return list(result.scalars().all())


async def list_attachments(db: AsyncSession, conversation_id: int) -> list[AssistantContextAttachment]:
    result = await db.execute(
        select(AssistantContextAttachment)
        .where(AssistantContextAttachment.conversation_id == conversation_id)
        .order_by(AssistantContextAttachment.id.asc())
    )
    return list(result.scalars().all())


async def append_message(
    db: AsyncSession,
    *,
    conversation_id: int,
    role: str,
    content: str,
    metadata_json: dict[str, Any] | None = None,
) -> AssistantMessage:
    msg = AssistantMessage(
        conversation_id=conversation_id,
        role=role,
        content=content,
        metadata_json=metadata_json,
    )
    db.add(msg)
    await db.flush()
    return msg


async def add_attachment(
    db: AsyncSession,
    *,
    conversation_id: int,
    attachment_type: str,
    resource_id: str,
    context_json: dict[str, Any] | None = None,
) -> AssistantContextAttachment:
    snap = await build_attachment_snapshot(
        db,
        attachment_type=attachment_type,
        resource_id=resource_id,
        context_json=context_json or {},
    )
    attachment = AssistantContextAttachment(
        conversation_id=conversation_id,
        attachment_type=snap["attachment_type"],
        resource_id=snap["resource_id"],
        label=snap.get("label"),
        context_json=snap.get("context_json"),
    )
    db.add(attachment)
    await db.commit()
    return attachment


async def add_uploaded_file_attachment(
    db: AsyncSession,
    *,
    conversation_id: int,
    filename: str,
    content: bytes,
    content_type: str | None = None,
) -> AssistantContextAttachment:
    convo = await get_conversation(db, conversation_id)
    safe_name = Path(filename or "attachment").name or "attachment"
    ext = Path(safe_name).suffix.lower()
    upload_dir = ASSISTANT_UPLOAD_DIR / str(convo.created_by) / str(conversation_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}{ext}"
    stored_path = upload_dir / stored_name
    stored_path.write_bytes(content)

    parse_error = None
    parsed = None
    try:
        parsed = await asyncio.to_thread(parse_document, str(stored_path))
    except Exception as exc:
        parse_error = f"{type(exc).__name__}: {exc}"

    full_text = ""
    parser_name = None
    if parsed is not None:
        parser_name = parsed.parser_name
        full_text = (parsed.full_text or "").strip()
        if not full_text and parsed.pages:
            page_bits = [page.content for page in parsed.pages if getattr(page, "content", None)]
            full_text = "\n\n".join(bit.strip() for bit in page_bits if bit and bit.strip())

    excerpt = full_text[:MAX_ASSISTANT_CONTEXT_CHARS]
    truncated = len(full_text) > len(excerpt)
    context_json = {
        "filename": safe_name,
        "content_type": content_type or "",
        "stored_path": str(stored_path),
        "file_size_bytes": len(content),
        "parser_name": parser_name,
        "extracted_text": excerpt,
        "extracted_text_truncated": truncated,
        "parse_error": parse_error,
        "has_text": bool(excerpt),
    }

    is_image = (content_type or "").lower().startswith("image/") or ext in IMAGE_SUFFIXES
    if is_image:
        try:
            vision_summary, vision_model = await _derive_image_context(
                db,
                stored_path=str(stored_path),
                filename=safe_name,
            )
            context_json["vision_summary"] = vision_summary
            context_json["vision_model"] = vision_model
        except Exception as exc:
            context_json["vision_error"] = f"{type(exc).__name__}: {exc}"

    attachment = AssistantContextAttachment(
        conversation_id=conversation_id,
        attachment_type="session_file",
        resource_id=stored_name,
        label=f"File: {safe_name}",
        context_json=context_json,
    )
    db.add(attachment)
    await db.commit()
    return attachment


async def _derive_image_context(
    db: AsyncSession,
    *,
    stored_path: str,
    filename: str,
) -> tuple[str, str]:
    provider, runtime = await build_provider_for_purpose(db, "chat_vision")
    vision_prompt = (
        f"Analyze the uploaded image named {filename}.\n"
        "Describe the visible content in a way that will help a later cybersecurity/compliance chat. "
        "Include visible text, UI labels, table contents, warnings, settings, diagrams, or screenshots when present."
    )
    if not hasattr(provider, "complete_multimodal"):
        raise RuntimeError("Configured vision provider does not support multimodal chat")
    summary = await provider.complete_multimodal(
        VISION_ATTACHMENT_SYSTEM_PROMPT,
        vision_prompt,
        [stored_path],
    )
    return summary.strip(), runtime.model


async def update_conversation_title(
    db: AsyncSession,
    *,
    conversation_id: int,
    title: str,
) -> AssistantConversation:
    convo = await get_conversation(db, conversation_id)
    convo.title = title.strip()[:255] or convo.title
    await db.commit()
    return await get_conversation(db, conversation_id)


async def delete_conversation(
    db: AsyncSession,
    *,
    conversation_id: int,
) -> None:
    convo = await get_conversation(db, conversation_id)
    attachments = await list_attachments(db, conversation_id)
    await db.delete(convo)
    await db.commit()
    for attachment in attachments:
        ctx = attachment.context_json or {}
        stored_path = ctx.get("stored_path")
        if stored_path:
            try:
                os.remove(stored_path)
            except FileNotFoundError:
                pass
            except Exception:
                pass


async def suggest_conversation_title(db: AsyncSession, conversation_id: int) -> str:
    attachments = await list_attachments(db, conversation_id)
    if attachments:
        first = attachments[0]
        if first.label:
            return first.label[:120]
        if first.attachment_type == "control":
            return f"Control {first.resource_id}"
        if first.attachment_type == "finding":
            return f"Finding {first.resource_id}"
        if first.attachment_type == "remediation":
            return "Remediation Assistant"
    convo = await get_conversation(db, conversation_id)
    if convo.mode == "workspace" and convo.project_id:
        return f"Project {convo.project_id} Assistant"
    return "Cyber Assistant"


async def build_attachment_snapshot(
    db: AsyncSession,
    *,
    attachment_type: str,
    resource_id: str,
    context_json: dict[str, Any],
) -> dict[str, Any]:
    attachment_type = (attachment_type or "general").strip().lower()
    resource_id = (resource_id or "").strip()
    context_json = dict(context_json or {})

    if attachment_type == "general":
        return {
            "attachment_type": "general",
            "resource_id": resource_id or "general",
            "label": "General Cyber Chat",
            "context_json": {},
        }

    if attachment_type == "project" and resource_id.isdigit():
        project = await db.get(Project, int(resource_id))
        if project:
            return {
                "attachment_type": "project",
                "resource_id": resource_id,
                "label": f"Project: {project.name}",
                "context_json": {
                    "project_id": project.id,
                    "project_name": project.name,
                    "impact_baseline": project.impact_baseline,
                    "system_type": project.system_type,
                },
            }

    if attachment_type == "provider" and resource_id.isdigit():
        provider = await db.get(CommonControlProvider, int(resource_id))
        if provider:
            return {
                "attachment_type": "provider",
                "resource_id": resource_id,
                "label": f"Provider: {provider.name}",
                "context_json": {
                    "provider_id": provider.id,
                    "name": provider.name,
                    "org_level": provider.org_level,
                    "description": provider.description,
                    "control_families": provider.control_families or [],
                },
            }

    if attachment_type == "library" and resource_id.isdigit():
        library_kind = (context_json.get("library_kind") or "").strip().lower()
        if library_kind == "policy":
            library = await db.get(PolicyLibrary, int(resource_id))
        elif library_kind == "procedure":
            library = await db.get(ProcedureLibrary, int(resource_id))
        else:
            library = None
        if library:
            return {
                "attachment_type": "library",
                "resource_id": resource_id,
                "label": f"{library_kind.title() if library_kind else 'Library'}: {library.name}",
                "context_json": {
                    "library_id": library.id,
                    "library_kind": library_kind,
                    "name": library.name,
                    "description": library.description,
                    "category": getattr(library, "category", None),
                },
            }

    if attachment_type == "document" and resource_id.isdigit():
        doc = await db.get(Document, int(resource_id))
        if doc:
            return {
                "attachment_type": "document",
                "resource_id": resource_id,
                "label": f"Document: {doc.filename}",
                "context_json": {
                    "document_id": doc.id,
                    "filename": doc.filename,
                    "parse_status": doc.parse_status,
                    "document_type": doc.document_type,
                    "document_intent": doc.document_intent,
                },
            }

    if attachment_type == "assessment" and resource_id.isdigit():
        assessment = await db.get(Assessment, int(resource_id))
        if assessment:
            counts_result = await db.execute(
                select(ControlFinding.status, func.count(ControlFinding.id))
                .where(ControlFinding.assessment_id == assessment.id)
                .group_by(ControlFinding.status)
            )
            counts = {status: count for status, count in counts_result.all()}
            return {
                "attachment_type": "assessment",
                "resource_id": resource_id,
                "label": f"Assessment: {assessment.name or f'Run #{assessment.project_run_number}'}",
                "context_json": {
                    "assessment_id": assessment.id,
                    "project_id": assessment.project_id,
                    "status": assessment.status,
                    "counts": counts,
                    "name": assessment.name,
                },
            }

    if attachment_type == "finding" and resource_id.isdigit():
        finding = await db.get(ControlFinding, int(resource_id))
        if finding:
            return {
                "attachment_type": "finding",
                "resource_id": resource_id,
                "label": f"{finding.control_id}: {finding.control_title}",
                "context_json": {
                    "assessment_id": finding.assessment_id,
                    "control_id": finding.control_id,
                    "control_title": finding.control_title,
                    "status": finding.status,
                    "gaps": finding.gaps or [],
                    "implementation_statement": finding.implementation_statement,
                    "llm_challenge_note": finding.llm_challenge_note,
                },
            }

    if attachment_type == "control":
        control_id = context_json.get("control_id") or resource_id
        label = context_json.get("label") or f"Control: {control_id}"
        try:
            from app.services.controls.catalog import load_catalog

            catalog = load_catalog()
            ctrl = next(
                (item for item in catalog.values() if item.label.upper() == str(control_id).upper()),
                None,
            )
            if ctrl:
                context_json.setdefault("control_title", ctrl.title)
                context_json.setdefault("control_statement", ctrl.statement)
                context_json.setdefault("objectives", ctrl.assessment_objectives[:12])
        except Exception:
            pass

        assessment_id = context_json.get("assessment_id")
        if assessment_id and control_id:
            result = await db.execute(
                select(ControlFinding).where(
                    ControlFinding.assessment_id == int(assessment_id),
                    ControlFinding.control_id == str(control_id),
                )
            )
            finding = result.scalar_one_or_none()
            if finding:
                context_json.setdefault("finding_status", finding.status)
                context_json.setdefault("finding_gaps", finding.gaps or [])
                context_json.setdefault("implementation_statement", finding.implementation_statement)
        return {
            "attachment_type": "control",
            "resource_id": control_id,
            "label": label,
            "context_json": context_json,
        }

    if attachment_type == "remediation":
        label = context_json.get("label") or "Remediation Context"
        report_id = context_json.get("report_id")
        if report_id:
            report = await db.get(RemediationReport, int(report_id))
            if report:
                label = label or f"Remediation: {report.report_type}"
                context_json = {
                    **context_json,
                    "assessment_id": report.assessment_id,
                    "report_type": report.report_type,
                    "status": report.status,
                }
        return {
            "attachment_type": "remediation",
            "resource_id": resource_id or str(report_id or context_json.get("assessment_id") or "remediation"),
            "label": label,
            "context_json": context_json,
        }

    if attachment_type == "admin_runtime":
        return {
            "attachment_type": "admin_runtime",
            "resource_id": resource_id or (context_json.get("setting_key") or "runtime"),
            "label": context_json.get("label") or "AI Runtime",
            "context_json": context_json,
        }

    if attachment_type == "evidence":
        return {
            "attachment_type": "evidence",
            "resource_id": resource_id or (context_json.get("evidence_id") or "evidence"),
            "label": context_json.get("label") or "Evidence",
            "context_json": context_json,
        }

    if attachment_type == "session_file":
        filename = context_json.get("filename") or resource_id or "attachment"
        return {
            "attachment_type": "session_file",
            "resource_id": resource_id or filename,
            "label": context_json.get("label") or f"File: {filename}",
            "context_json": context_json,
        }

    return {
        "attachment_type": attachment_type,
        "resource_id": resource_id,
        "label": context_json.get("label") or attachment_type.replace("_", " ").title(),
        "context_json": context_json,
    }


async def build_context_block(db: AsyncSession, conversation_id: int) -> str:
    convo = await get_conversation(db, conversation_id)
    attachments = await list_attachments(db, conversation_id)
    lines: list[str] = []

    if convo.project_id:
        project = await db.get(Project, convo.project_id)
        if project:
            lines.append(f"Project: {project.name} (baseline: {project.impact_baseline})")

    if convo.assessment_id:
        assessment = await db.get(Assessment, convo.assessment_id)
        if assessment:
            lines.append(
                f"Assessment: {assessment.name or f'Run #{assessment.project_run_number}'} "
                f"(status: {assessment.status})"
            )

    for attachment in attachments:
        ctx = attachment.context_json or {}
        lines.append(f"Context Attachment: {attachment.label or attachment.attachment_type}")
        if attachment.attachment_type == "finding":
            if ctx.get("control_id"):
                lines.append(
                    f"Control: {ctx.get('control_id')} - {ctx.get('control_title') or ''}".rstrip()
                )
            if ctx.get("status"):
                lines.append(f"Current Status: {str(ctx['status']).replace('_', ' ')}")
            if ctx.get("llm_challenge_note"):
                lines.append(f"Challenge Note: {ctx['llm_challenge_note']}")
            if ctx.get("gaps"):
                lines.append("Gaps: " + "; ".join(ctx["gaps"][:8]))
            if ctx.get("implementation_statement"):
                lines.append(f"Implementation Statement: {ctx['implementation_statement'][:1200]}")
        elif attachment.attachment_type == "control":
            if ctx.get("control_id"):
                lines.append(f"Control: {ctx['control_id']}")
            if ctx.get("control_title"):
                lines.append(f"Title: {ctx['control_title']}")
            if ctx.get("control_statement"):
                lines.append(f"Statement: {ctx['control_statement'][:1200]}")
            objectives = ctx.get("objectives") or []
            if objectives:
                lines.append("Assessment Objectives:")
                lines.extend(f"- {obj}" for obj in objectives[:12])
            if ctx.get("finding_status"):
                lines.append(f"Current Finding Status: {ctx['finding_status']}")
            if ctx.get("finding_gaps"):
                lines.append("Identified Gaps: " + "; ".join(ctx["finding_gaps"][:8]))
        elif attachment.attachment_type == "remediation":
            if ctx.get("report_type"):
                lines.append(f"Remediation Report Type: {ctx['report_type']}")
            if ctx.get("finding_summary"):
                lines.append(f"Gap Summary: {ctx['finding_summary']}")
            if ctx.get("target_package_style"):
                lines.append(f"Package Style: {ctx['target_package_style']}")
        elif attachment.attachment_type == "assessment":
            if ctx.get("counts"):
                counts = ctx["counts"]
                parts = ", ".join(f"{k}: {v}" for k, v in counts.items())
                lines.append(f"Assessment Counts: {parts}")
        elif attachment.attachment_type == "provider":
            if ctx.get("name"):
                lines.append(f"Common Control Provider: {ctx['name']}")
            if ctx.get("org_level"):
                lines.append(f"Provider Level: {ctx['org_level']}")
            if ctx.get("control_families"):
                lines.append("Covered Families: " + ", ".join(ctx["control_families"][:12]))
            if ctx.get("description"):
                lines.append(f"Description: {ctx['description'][:800]}")
        elif attachment.attachment_type == "library":
            if ctx.get("library_kind"):
                lines.append(f"Library Type: {ctx['library_kind']}")
            if ctx.get("name"):
                lines.append(f"Library Name: {ctx['name']}")
            if ctx.get("category"):
                lines.append(f"Category: {ctx['category']}")
            if ctx.get("description"):
                lines.append(f"Description: {ctx['description'][:800]}")
        elif attachment.attachment_type == "document":
            if ctx.get("filename"):
                lines.append(f"Document: {ctx['filename']}")
            if ctx.get("parse_status"):
                lines.append(f"Parse Status: {ctx['parse_status']}")
            if ctx.get("document_type"):
                lines.append(f"Document Type: {ctx['document_type']}")
            if ctx.get("document_intent"):
                lines.append(f"Document Intent: {ctx['document_intent']}")
        elif attachment.attachment_type == "admin_runtime":
            if ctx.get("setting_key"):
                lines.append(f"Runtime Setting: {ctx['setting_key']}")
            if ctx.get("setting_value"):
                lines.append(f"Current Value: {ctx['setting_value']}")
        elif attachment.attachment_type == "evidence":
            if ctx.get("excerpt"):
                lines.append(f"Evidence Excerpt: {ctx['excerpt'][:1200]}")
            if ctx.get("source_label"):
                lines.append(f"Source: {ctx['source_label']}")
        elif attachment.attachment_type == "session_file":
            if ctx.get("filename"):
                lines.append(f"Uploaded File: {ctx['filename']}")
            if ctx.get("content_type"):
                lines.append(f"Content Type: {ctx['content_type']}")
            if ctx.get("parser_name"):
                lines.append(f"Parsed By: {ctx['parser_name']}")
            if ctx.get("parse_error"):
                lines.append(f"Parse Error: {ctx['parse_error']}")
            if ctx.get("vision_model"):
                lines.append(f"Vision Model: {ctx['vision_model']}")
            if ctx.get("vision_error"):
                lines.append(f"Vision Derivation Error: {ctx['vision_error']}")
            if ctx.get("vision_summary"):
                lines.append(f"Derived Image Context:\n{ctx['vision_summary'][:3000]}")
            if ctx.get("extracted_text"):
                text = ctx["extracted_text"]
                if ctx.get("extracted_text_truncated"):
                    text += "\n[Truncated for chat context]"
                lines.append(f"Uploaded File Text:\n{text}")

    return "\n".join(lines) if lines else "No attached project context."


def serialize_message(message: AssistantMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "metadata_json": message.metadata_json or {},
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def serialize_attachment(attachment: AssistantContextAttachment) -> dict[str, Any]:
    return {
        "id": attachment.id,
        "attachment_type": attachment.attachment_type,
        "resource_id": attachment.resource_id,
        "label": attachment.label,
        "context_json": attachment.context_json or {},
    }


def serialize_conversation(convo: AssistantConversation) -> dict[str, Any]:
    return {
        "id": convo.id,
        "mode": convo.mode,
        "title": convo.title,
        "project_id": convo.project_id,
        "assessment_id": convo.assessment_id,
        "created_at": convo.created_at.isoformat() if convo.created_at else None,
        "updated_at": convo.updated_at.isoformat() if convo.updated_at else None,
    }


async def serialize_conversation_summary(
    db: AsyncSession,
    convo: AssistantConversation,
) -> dict[str, Any]:
    attachments = await list_attachments(db, convo.id)
    latest_result = await db.execute(
        select(AssistantMessage)
        .where(AssistantMessage.conversation_id == convo.id)
        .order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc())
        .limit(1)
    )
    latest = latest_result.scalar_one_or_none()
    preview = None
    if latest:
        preview = (latest.content or "").strip().replace("\n", " ")
        if len(preview) > 120:
            preview = preview[:117] + "..."
    return {
        **serialize_conversation(convo),
        "attachment_labels": [a.label for a in attachments if a.label][:4],
        "message_count": (
            await db.scalar(
                select(func.count(AssistantMessage.id)).where(
                    AssistantMessage.conversation_id == convo.id
                )
            )
        ) or 0,
        "last_message_preview": preview,
    }
