"""
Procedure Categorizer — LLM-powered document categorization for Enterprise Procedures.

After a procedure document is uploaded, this service:
  1. Reads the document title + early parsed text as context
  2. Calls the LLM to determine which procedure category the document belongs to
  3. Gets or auto-creates the matching ProcedureLibrary
  4. Assigns the document to that library
  5. Triggers the staged ingestion pipeline
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import select

from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

PROCEDURE_CATEGORIES = {
    "general":                  "General Procedures",
    "access_management":        "Access Management",
    "change_management":        "Change Management",
    "incident_management":      "Incident Management",
    "backup_recovery":          "Backup & Recovery",
    "configuration_management": "Configuration Management",
    "vulnerability_management": "Vulnerability Management",
    "patch_management":         "Patch Management",
    "identity_management":      "Identity Management",
    "continuous_monitoring":    "Continuous Monitoring",
    "system_authorization":     "System Authorization",
}

CATEGORIZE_SYSTEM_PROMPT = """You are a compliance document analyst specializing in NIST 800-53 system security procedures.

Your task: given a document filename and text excerpts, classify the document into EXACTLY ONE of the following procedure categories.

CATEGORIES:
- general: General operational procedures not fitting other categories
- access_management: User access provisioning, deprovisioning, access reviews, privileged access, role management
- change_management: Change requests, change control board, testing, rollback, release management
- incident_management: Security incident detection, response, escalation, recovery, breach notification
- backup_recovery: Data backup schedules, restoration testing, disaster recovery, business continuity
- configuration_management: System configuration, baseline hardening, configuration drift, CMDB
- vulnerability_management: Vulnerability scanning, risk rating, remediation tracking, CVE handling
- patch_management: Software/firmware patching, patch testing, emergency patching, deployment schedules
- identity_management: Identity lifecycle, MFA enrollment, SSO, credential management, PKI
- continuous_monitoring: Ongoing security monitoring, log review, metric reporting, POA&M review
- system_authorization: ATO/RMF process, security authorization, FedRAMP assessment, ISSO activities

Return ONLY the category identifier (e.g., "access_management"). No explanation, no punctuation, nothing else."""


def _parse_category(raw: str) -> str:
    """Extract a valid category from LLM response."""
    raw = raw.strip().lower()
    # Try exact match first
    if raw in PROCEDURE_CATEGORIES:
        return raw
    # Try to find any category name in the response
    for cat in PROCEDURE_CATEGORIES:
        if cat in raw:
            return cat
    return "general"


async def _get_or_create_library(category: str, db) -> int:
    """Return the ID of the ProcedureLibrary for this category, creating it if needed."""
    from app.models.orm import ProcedureLibrary

    result = await db.execute(
        select(ProcedureLibrary).where(ProcedureLibrary.category == category)
    )
    lib = result.scalar_one_or_none()
    if lib:
        return lib.id

    # Auto-create the library for this category (system-managed, no created_by)
    lib = ProcedureLibrary(
        name=PROCEDURE_CATEGORIES.get(category, category.replace("_", " ").title()),
        description=f"Auto-created library for {PROCEDURE_CATEGORIES.get(category, category)} procedures.",
        category=category,
        created_by=None,  # system-created
    )
    db.add(lib)
    await db.flush()  # get the ID without committing
    return lib.id


async def categorize_and_tag(document_id: int) -> None:
    """
    Full pipeline for procedure documents:
      inspect file → categorize → assign library → run ingestion pipeline
    """
    from app.core.config import get_settings
    from app.models.orm import Document
    from app.services.ingestion.line_parser import extract_lines
    from app.services.parsers.dispatcher import parse_document

    settings = get_settings()

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return

        # Mark as categorizing
        doc.parse_status = "categorizing"
        await db.commit()

    try:
        parsed = parse_document(doc.file_path)
        if not parsed.success:
            raise RuntimeError(parsed.error or "Procedure parse failed")
        lines = extract_lines(parsed)[:24]

        # Build the user prompt from filename + chunk text
        context_parts = [f"Document filename: {doc.filename}"]
        for line in lines:
            if line.section_path:
                context_parts.append(f"\n[Section: {line.section_path}]")
            context_parts.append((line.content or "")[:600])

        user_prompt = (
            "Classify this procedure document into the correct category.\n\n"
            + "\n".join(context_parts)[:4000]
        )

        # Call LLM
        from app.services.llm.runtime import build_provider_for_purpose
        from app.services.prompt_manager import get_prompt

        async with AsyncSessionLocal() as cfg_db:
            llm, _ = await build_provider_for_purpose(
                cfg_db,
                "procedure_categorization",
                provider_name=settings.default_llm_provider,
            )
        system_prompt = await get_prompt("procedure_categorization", CATEGORIZE_SYSTEM_PROMPT)
        raw = await llm.complete(system_prompt, user_prompt)
        category = _parse_category(raw)

        logger.info("Document %s categorized as: %s", document_id, category)

        # Get or create the library, then assign document
        async with AsyncSessionLocal() as db:
            library_id = await _get_or_create_library(category, db)

            doc_result = await db.execute(select(Document).where(Document.id == document_id))
            doc = doc_result.scalar_one_or_none()
            if doc:
                doc.procedure_library_id = library_id
                doc.parse_status = "pending"
                doc.parse_error = None
            await db.commit()

    except Exception as e:
        logger.error("Categorization failed for document %s: %s", document_id, e)
        async with AsyncSessionLocal() as db:
            doc_result = await db.execute(select(Document).where(Document.id == document_id))
            doc = doc_result.scalar_one_or_none()
            if doc:
                # Fall back to general category
                library_id = await _get_or_create_library("general", db)
                doc.procedure_library_id = library_id
                doc.parse_status = "pending"
                doc.parse_error = f"Auto-categorization failed ({str(e)[:200]}), assigned to General."
            await db.commit()

    from app.services.ingestion.pipeline import run_ingestion_pipeline
    await run_ingestion_pipeline(document_id)
