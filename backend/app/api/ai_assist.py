"""AI-assisted content generation for notes and rationale fields."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_assessor
from app.models.orm import Assessment, ControlFinding

router = APIRouter(prefix="/ai-assist", tags=["ai-assist"])

SECTION_PROMPTS = {
    "control_notes": (
        "You are an experienced ISSO writing concise analyst notes for a security control finding.\n"
        "Write 2–4 sentences of professional notes suitable for a control assessor reviewing this finding. "
        "Summarize the key compliance status, the most significant gap or evidence, and the recommended next action. "
        "Be specific, factual, and avoid generalities. Do not use bullet points — write in plain prose."
    ),
    "assessment_notes": (
        "You are an experienced ISSO writing a brief narrative summary for a completed security assessment run.\n"
        "Write 3–5 sentences summarizing the overall assessment results. Reference the compliance counts provided. "
        "Note any significant findings, areas of concern, or positive results. "
        "Be concise and professional. Plain prose only."
    ),
    "applicability_rationale": (
        "You are an experienced ISSO documenting the rationale for a control applicability determination.\n"
        "Write 1–3 sentences explaining why this control is or is not applicable to this system. "
        "Reference any relevant system characteristics (cloud-hosted, FedRAMP-inherited, etc.). "
        "Be specific and cite the control family."
    ),
    "satisfied_rationale": (
        "You are an experienced ISSO documenting why a security control is marked 'Satisfied' and should be excluded from future automated assessments.\n"
        "Write 2–3 sentences explaining the basis for this determination, what evidence was reviewed, "
        "and any conditions that would require re-assessment. Be precise and professional."
    ),
    "risk_rationale": (
        "You are an experienced ISSO writing a formal risk acceptance rationale for an ISSO/AO signature.\n"
        "Write 3–5 sentences: (1) describe the residual risk, (2) identify the business/mission justification for accepting it, "
        "(3) note any compensating controls in place, (4) recommend a review timeframe. "
        "Use formal, FISMA-appropriate language."
    ),
    "manual_status_rationale": (
        "You are an experienced ISSO documenting the basis for manually overriding an automated compliance determination.\n"
        "Write 2–3 sentences citing specific evidence (document names, sections, dates) that support the manually-set status. "
        "Be precise — vague statements are not acceptable for audit purposes."
    ),
}


class DissentChatRequest(BaseModel):
    finding_id: int
    messages: list[dict]  # [{role: "user"|"assistant", content: str}]


class AiAssistRequest(BaseModel):
    section: str            # one of the SECTION_PROMPTS keys
    project_id: int | None = None
    finding_id: int | None = None
    assessment_id: int | None = None
    # extra context the frontend can pass directly
    control_id: str | None = None
    control_title: str | None = None
    current_status: str | None = None
    target_status: str | None = None
    gaps: list[str] | None = None
    implementation_statement: str | None = None
    assessment_stats: dict | None = None  # {compliant, partial, non_compliant, na, total}


class AiAssistResponse(BaseModel):
    text: str


@router.post("/notes", response_model=AiAssistResponse)
async def generate_notes(
    body: AiAssistRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> AiAssistResponse:
    if body.section not in SECTION_PROMPTS:
        raise HTTPException(status_code=400, detail=f"Unknown section '{body.section}'. "
                            f"Valid: {list(SECTION_PROMPTS.keys())}")

    from app.services.prompt_manager import get_prompt
    system_prompt = await get_prompt(body.section, SECTION_PROMPTS[body.section])

    # Build context block from DB + request fields
    context_lines = []

    # Load finding from DB if finding_id provided
    finding = None
    if body.finding_id:
        result = await db.execute(select(ControlFinding).where(ControlFinding.id == body.finding_id))
        finding = result.scalar_one_or_none()

    if finding:
        context_lines += [
            f"Control: {finding.control_id} — {finding.control_title}",
            f"Family: {finding.control_family}",
            f"Assessment Status: {finding.status.replace('_', ' ').title()}",
            f"Confidence: {finding.confidence_score:.0%}",
        ]
        if finding.implementation_statement:
            context_lines.append(f"Implementation Statement: {finding.implementation_statement[:600]}")
        if finding.gaps:
            gaps_text = "; ".join(finding.gaps[:5])
            context_lines.append(f"Identified Gaps: {gaps_text}")
        if finding.rule_signal:
            context_lines.append(f"Keyword Signal: {finding.rule_signal}")
    else:
        # Use fields supplied directly in request
        if body.control_id:
            context_lines.append(f"Control: {body.control_id}" + (f" — {body.control_title}" if body.control_title else ""))
        if body.current_status:
            context_lines.append(f"Current Status: {body.current_status.replace('_', ' ').title()}")
        if body.target_status:
            context_lines.append(f"New Status: {body.target_status.replace('_', ' ').title()}")
        if body.gaps:
            context_lines.append(f"Identified Gaps: {'; '.join(body.gaps[:5])}")
        if body.implementation_statement:
            context_lines.append(f"Implementation Statement: {body.implementation_statement[:600]}")

    if body.assessment_stats:
        s = body.assessment_stats
        context_lines.append(
            f"Assessment Results: {s.get('compliant',0)} Compliant, {s.get('partial',0)} Partial, "
            f"{s.get('non_compliant',0)} Non-Compliant, {s.get('na',0)} N/A out of {s.get('total',0)} controls"
        )

    context_block = "\n".join(context_lines) if context_lines else "No additional context provided."
    user_prompt = f"Context:\n{context_block}\n\nGenerate the {body.section.replace('_', ' ')} now. Return only the text — no labels, no JSON, no preamble."

    try:
        from app.services.llm.runtime import build_provider_for_purpose

        provider, _ = await build_provider_for_purpose(db, "ai_assist_notes")
        text = (await provider.complete(system_prompt, user_prompt)).strip()
        # Strip any JSON wrapping if model misbehaves
        if text.startswith("{") or text.startswith('"'):
            import json, re
            m = re.search(r'"([^"]{20,})"', text)
            text = m.group(1) if m else text
        return AiAssistResponse(text=text)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI generation failed: {e}")


@router.post("/dissent-chat", response_model=AiAssistResponse)
async def dissent_chat(
    body: DissentChatRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> AiAssistResponse:
    """Multi-turn AI collaboration on a challenged assessment verdict.

    The LLM's dissent note is injected into every system prompt so the
    conversation is always fully grounded in the specific finding's context.
    The automated verdict is never altered by this endpoint — the analyst
    can formally override it via the assessment controls if they agree.
    """
    result = await db.execute(select(ControlFinding).where(ControlFinding.id == body.finding_id))
    finding = result.scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    if not finding.llm_challenge_note:
        raise HTTPException(status_code=400, detail="This finding has no AI dissent to discuss")

    # Load control statement and objectives from catalog for richer context
    control_statement = ""
    obj_text = ""
    try:
        from app.services.controls.catalog import load_catalog
        catalog = load_catalog()
        ctrl = next(
            (c for c in catalog.values() if c.label.upper() == finding.control_id.upper()),
            None,
        )
        if ctrl:
            control_statement = ctrl.statement[:600]
            objectives = ctrl.assessment_objectives[:15]
            if objectives:
                obj_text = "\n".join(f"  {o}" for o in objectives)
    except Exception:
        pass

    gaps_text = (
        "\n".join(f"• {g}" for g in finding.gaps)
        if finding.gaps else "None identified"
    )

    system_prompt = f"""You are a senior NIST 800-53 Rev 5 security assessor collaborating with a compliance analyst. You reviewed an automated assessment verdict and recorded a dissent — meaning you believe the verdict may be incorrect or warrants closer scrutiny based on the evidence evaluated.

CONTROL CONTEXT:
Control ID: {finding.control_id}
Title: {finding.control_title}
Family: {finding.control_family}
{"Control Statement: " + control_statement if control_statement else ""}
{("Assessment Objectives (800-53A):" + chr(10) + obj_text) if obj_text else ""}

AUTOMATED VERDICT (code-anchored, remains authoritative unless analyst overrides):
Status: {finding.status.replace("_", " ").title()}
Confidence: {f"{finding.confidence_score:.0%}" if finding.confidence_score else "N/A"}

IMPLEMENTATION STATEMENT (from assessment):
{finding.implementation_statement or "Not recorded."}

IDENTIFIED GAPS:
{gaps_text}

YOUR DISSENT NOTE (what you flagged):
{finding.llm_challenge_note}

YOUR ROLE IN THIS CONVERSATION:
• Explain precisely why you challenged the verdict, referencing specific objective IDs
• Describe what evidence would satisfy each unmet objective
• Suggest concrete, actionable remediation steps tailored to these gaps
• Help draft updated implementation statements, SSP language, or POAM entries if asked
• If the analyst provides additional context that changes the picture, acknowledge it clearly
• Be direct and practical — avoid generic NIST boilerplate
• Do not repeat the dissent note verbatim; build on it conversationally

The verdict remains as assessed until the analyst formally overrides it. Your goal is to give them everything they need to make an informed decision."""

    # Build Ollama messages: system prompt + capped conversation history
    ollama_messages = [
        {"role": "system", "content": system_prompt},
        *[
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in body.messages[-20:]
        ],
    ]

    try:
        from app.services.llm.runtime import resolve_llm_runtime
        from ollama import AsyncClient

        runtime = await resolve_llm_runtime(db, "dissent_chat", provider_name="ollama")
        client = AsyncClient(host=(runtime.base_url or "").rstrip("/"))
        response = await client.chat(
            model=runtime.model,
            messages=ollama_messages,
            options={"temperature": 0.35, "num_ctx": 8192, "reasoning_effort": runtime.reasoning_effort or "high"},
            think=(runtime.reasoning_effort or "high") in {"medium", "high"},
        )
        return AiAssistResponse(text=response.message.content.strip())
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI collaboration failed: {e}")
