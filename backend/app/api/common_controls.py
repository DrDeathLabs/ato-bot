"""Common Control Providers API — enterprise-shared controls library."""
from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.documents import ALLOWED_EXTENSIONS, _get_file_type
from app.core.config import get_settings
from app.core.database import get_db
from app.core.rbac import require_admin, require_assessor, require_project_access, require_viewer
from app.models.orm import (
    CommonControlProvider,
    Document,
    ProjectCommonProvider,
)
from app.services.evidence_view import get_document_evidence_payload

router = APIRouter(prefix="/common-controls", tags=["common-controls"])
settings = get_settings()


# ── Schemas ───────────────────────────────────────────────────────────────────

class ProviderCreate(BaseModel):
    name: str
    description: str | None = None
    org_level: str = "enterprise"
    control_families: list[str] | None = None


class ProviderUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    org_level: str | None = None
    control_families: list[str] | None = None


class ProviderResponse(BaseModel):
    id: int
    name: str
    description: str | None
    org_level: str
    control_families: list[str] | None
    created_at: str
    document_count: int = 0

    model_config = {"from_attributes": True}


# ── Providers CRUD ────────────────────────────────────────────────────────────

@router.get("/providers")
async def list_providers(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> list[dict]:
    result = await db.execute(
        select(CommonControlProvider).order_by(CommonControlProvider.name)
    )
    providers = result.scalars().all()
    out = []
    for p in providers:
        doc_result = await db.execute(
            select(Document.id).where(Document.provider_id == p.id)
        )
        doc_count = len(doc_result.fetchall())
        out.append({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "org_level": p.org_level,
            "control_families": p.control_families or [],
            "created_at": p.created_at.isoformat(),
            "document_count": doc_count,
        })
    return out


@router.post("/providers", status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: ProviderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> dict:
    provider = CommonControlProvider(
        name=body.name,
        description=body.description,
        org_level=body.org_level,
        control_families=body.control_families,
        created_by=current_user["id"],
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return {"id": provider.id, "name": provider.name, "description": provider.description,
            "org_level": provider.org_level, "control_families": provider.control_families or [],
            "created_at": provider.created_at.isoformat(), "document_count": 0}


@router.patch("/providers/{provider_id}")
async def update_provider(
    provider_id: int,
    body: ProviderUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
) -> dict:
    result = await db.execute(
        select(CommonControlProvider).where(CommonControlProvider.id == provider_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    if body.name is not None:
        provider.name = body.name
    if body.description is not None:
        provider.description = body.description
    if body.org_level is not None:
        provider.org_level = body.org_level
    if body.control_families is not None:
        provider.control_families = body.control_families
    await db.commit()
    return {"id": provider.id, "name": provider.name}


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
) -> None:
    result = await db.execute(
        select(CommonControlProvider).where(CommonControlProvider.id == provider_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    # Delete all uploaded files from disk
    doc_result = await db.execute(
        select(Document).where(Document.provider_id == provider_id)
    )
    for doc in doc_result.scalars().all():
        try:
            os.unlink(doc.file_path)
        except FileNotFoundError:
            pass
    await db.delete(provider)
    await db.commit()


# ── Provider Documents ────────────────────────────────────────────────────────

@router.get("/providers/{provider_id}/processing-progress")
async def get_provider_processing_progress(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    """Return ingestion pipeline stage progress for all processing docs in this provider."""
    from app.models.orm import IngestionRun
    from sqlalchemy import desc
    result = await db.execute(
        select(Document.id).where(Document.provider_id == provider_id, Document.parse_status == "processing")
    )
    ids = [r[0] for r in result.fetchall()]
    if not ids:
        return {}
    progress = {}
    for doc_id in ids:
        run_r = await db.execute(
            select(IngestionRun).where(IngestionRun.document_id == doc_id, IngestionRun.status == "running")
            .order_by(desc(IngestionRun.started_at)).limit(1)
        )
        run = run_r.scalar_one_or_none()
        if not run:
            progress[doc_id] = {"stage": "parse", "pct": 0}
            continue
        completed = sum(1 for s in ["stage_parse","stage_screen","stage_expand","stage_classify","stage_embed"] if getattr(run, s) == "complete")
        progress[doc_id] = {
            "stage": run.current_stage or "parse",
            "stage_parse": run.stage_parse, "stage_screen": run.stage_screen,
            "stage_expand": run.stage_expand, "stage_classify": run.stage_classify,
            "stage_embed": run.stage_embed,
            "lines_parsed": run.lines_parsed, "evidence_units": run.evidence_units_created,
            "units_classified": run.units_classified, "pct": completed * 20,
        }
    return progress


@router.get("/providers/{provider_id}/documents")
async def list_provider_documents(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> list[dict]:
    result = await db.execute(
        select(Document)
        .where(Document.provider_id == provider_id)
        .order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    return [_doc_dict(d) for d in docs]


@router.post("/providers/{provider_id}/documents",
             status_code=status.HTTP_201_CREATED)
async def upload_provider_document(
    provider_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
) -> dict:
    result = await db.execute(
        select(CommonControlProvider).where(CommonControlProvider.id == provider_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Provider not found")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type not allowed: {suffix}")

    content = await file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_size_mb}MB limit")

    file_hash = hashlib.sha256(content).hexdigest()
    existing = await db.execute(
        select(Document).where(Document.provider_id == provider_id, Document.file_hash == file_hash)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="File already uploaded to this provider")

    upload_dir = Path(settings.upload_dir) / f"cc_{provider_id}"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{uuid.uuid4().hex}{suffix}"
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    doc = Document(
        provider_id=provider_id,
        project_id=None,
        filename=file.filename,
        file_path=str(file_path),
        file_type=_get_file_type(file.filename),
        file_hash=file_hash,
        file_size_bytes=len(content),
        parse_status="pending",
        uploaded_by=current_user["id"],
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    from app.services.parsers.dispatcher import dispatch_parse
    asyncio.create_task(dispatch_parse(doc.id))

    return _doc_dict(doc)


@router.post("/providers/{provider_id}/documents/{doc_id}/reparse")
async def reparse_provider_document(
    provider_id: int,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> dict:
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.provider_id == provider_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not Path(doc.file_path).exists():
        raise HTTPException(status_code=409, detail="File no longer exists on disk — please re-upload")
    doc.parse_status = "pending"
    doc.parse_error = None
    await db.commit()
    from app.services.parsers.dispatcher import dispatch_parse
    asyncio.create_task(dispatch_parse(doc.id))
    return _doc_dict(doc)


@router.post("/providers/{provider_id}/documents/{doc_id}/reindex")
async def reindex_provider_document(
    provider_id: int,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> dict:
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.provider_id == provider_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.parse_status in ("pending", "processing", "indexing"):
        raise HTTPException(status_code=409, detail="Document is already being processed")
    if doc.parse_status == "failed":
        raise HTTPException(status_code=409, detail="Document parse failed — reparse first before indexing")
    doc.parse_status = "pending"
    doc.parse_error = None
    await db.commit()
    from app.services.ingestion.pipeline import run_ingestion_pipeline
    asyncio.create_task(run_ingestion_pipeline(document_id=doc.id))
    return _doc_dict(doc)


@router.delete("/providers/{provider_id}/documents/{doc_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_document(
    provider_id: int,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> None:
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.provider_id == provider_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        os.unlink(doc.file_path)
    except FileNotFoundError:
        pass
    await db.delete(doc)
    await db.commit()


@router.get("/providers/{provider_id}/documents/{doc_id}/chunks")
async def get_provider_document_chunks(
    provider_id: int,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> dict:
    """Return evidence excerpts with control mappings for a provider document."""

    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.provider_id == provider_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    payload = await get_document_evidence_payload(doc_id, db)
    return payload or {
        "document_id": doc.id,
        "filename": doc.filename,
        "parse_status": doc.parse_status,
        "parse_error": doc.parse_error,
        "total_chunks": 0,
        "total_tags": 0,
        "unique_controls": 0,
        "chunks": [],
    }


@router.get("/providers/{provider_id}/documents/{doc_id}/download")
async def download_provider_document(
    provider_id: int,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    from fastapi.responses import FileResponse as FR
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.provider_id == provider_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not Path(doc.file_path).exists():
        raise HTTPException(status_code=410, detail="File no longer exists on disk")
    return FR(path=doc.file_path, filename=doc.filename, media_type="application/octet-stream")


# ── Project ↔ Provider linking ────────────────────────────────────────────────

@router.get("/projects/{project_id}/providers")
async def get_project_providers(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_access),
    _: dict = Depends(require_viewer),
) -> list[dict]:
    result = await db.execute(
        select(ProjectCommonProvider, CommonControlProvider)
        .join(CommonControlProvider, ProjectCommonProvider.provider_id == CommonControlProvider.id)
        .where(ProjectCommonProvider.project_id == project_id)
    )
    rows = result.fetchall()
    out = []
    for link, provider in rows:
        doc_result = await db.execute(
            select(Document.id).where(
                Document.provider_id == provider.id,
                Document.parse_status == "complete",
            )
        )
        doc_count = len(doc_result.fetchall())
        out.append({
            "id": provider.id,
            "name": provider.name,
            "description": provider.description,
            "org_level": provider.org_level,
            "control_families": provider.control_families or [],
            "linked_at": link.linked_at.isoformat(),
            "document_count": doc_count,
        })
    return out


@router.post("/projects/{project_id}/providers/{provider_id}",
             status_code=status.HTTP_201_CREATED)
async def link_provider_to_project(
    project_id: int,
    provider_id: int,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_access),
    current_user: dict = Depends(require_assessor),
) -> dict:
    existing = await db.execute(
        select(ProjectCommonProvider).where(
            ProjectCommonProvider.project_id == project_id,
            ProjectCommonProvider.provider_id == provider_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Provider already linked to this project")
    link = ProjectCommonProvider(
        project_id=project_id,
        provider_id=provider_id,
        linked_by=current_user["id"],
    )
    db.add(link)
    await db.commit()
    return {"project_id": project_id, "provider_id": provider_id, "linked": True}


@router.delete("/projects/{project_id}/providers/{provider_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def unlink_provider_from_project(
    project_id: int,
    provider_id: int,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_access),
    _: dict = Depends(require_assessor),
) -> None:
    result = await db.execute(
        select(ProjectCommonProvider).where(
            ProjectCommonProvider.project_id == project_id,
            ProjectCommonProvider.provider_id == provider_id,
        )
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    await db.delete(link)
    await db.commit()


# ── Helper ────────────────────────────────────────────────────────────────────

def _doc_dict(doc: Document) -> dict:
    return {
        "id": doc.id,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "file_size_bytes": doc.file_size_bytes,
        "parse_status": doc.parse_status,
        "parse_error": doc.parse_error,
        "page_count": doc.page_count,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }
