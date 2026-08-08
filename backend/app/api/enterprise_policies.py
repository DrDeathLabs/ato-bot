"""Enterprise Policy Library API — organization-wide policy document management."""
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

from app.core.config import get_settings
from app.core.database import get_db
from app.core.rbac import require_assessor, require_viewer
from app.services.evidence_view import get_document_evidence_payload

settings = get_settings()

ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".vsdx", ".vsd", ".txt", ".md", ".png", ".jpg", ".jpeg",
    ".gif", ".tiff", ".bmp",
}

POLICY_CATEGORIES = [
    "general",
    "information_security",
    "access_control",
    "configuration_management",
    "incident_response",
    "contingency_planning",
    "personnel_security",
    "risk_management",
    "supply_chain",
    "privacy",
]

router = APIRouter(prefix="/enterprise-policies", tags=["enterprise-policies"])


class LibraryCreate(BaseModel):
    name: str
    description: str | None = None
    category: str = "general"


class LibraryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None


def _doc_dict(doc) -> dict:
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


def _lib_dict(lib, doc_count: int = 0) -> dict:
    return {
        "id": lib.id,
        "name": lib.name,
        "description": lib.description,
        "category": lib.category,
        "document_count": doc_count,
        "created_at": lib.created_at.isoformat() if lib.created_at else None,
    }


def _get_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    return ext or "unknown"


# ── Library CRUD ───────────────────────────────────────────────────────────────

@router.get("/libraries")
async def list_libraries(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> list[dict]:
    from app.models.orm import PolicyLibrary, Document
    from sqlalchemy import func as sqlfunc

    result = await db.execute(
        select(
            PolicyLibrary,
            sqlfunc.count(Document.id).label("doc_count"),
        )
        .outerjoin(Document, Document.policy_library_id == PolicyLibrary.id)
        .group_by(PolicyLibrary.id)
        .order_by(PolicyLibrary.name)
    )
    rows = result.all()
    return [_lib_dict(lib, count) for lib, count in rows]


@router.post("/libraries", status_code=status.HTTP_201_CREATED)
async def create_library(
    body: LibraryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
) -> dict:
    from app.models.orm import PolicyLibrary

    if body.category not in POLICY_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category. Must be one of: {', '.join(POLICY_CATEGORIES)}")

    lib = PolicyLibrary(
        name=body.name.strip(),
        description=body.description,
        category=body.category,
        created_by=current_user["id"],
    )
    db.add(lib)
    await db.commit()
    await db.refresh(lib)
    return _lib_dict(lib)


@router.patch("/libraries/{library_id}")
async def update_library(
    library_id: int,
    body: LibraryUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> dict:
    from app.models.orm import PolicyLibrary

    result = await db.execute(select(PolicyLibrary).where(PolicyLibrary.id == library_id))
    lib = result.scalar_one_or_none()
    if not lib:
        raise HTTPException(status_code=404, detail="Policy library not found")

    if body.name is not None:
        lib.name = body.name.strip()
    if body.description is not None:
        lib.description = body.description
    if body.category is not None:
        if body.category not in POLICY_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"Invalid category.")
        lib.category = body.category

    await db.commit()
    await db.refresh(lib)
    return _lib_dict(lib)


@router.delete("/libraries/{library_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_library(
    library_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> None:
    from app.models.orm import PolicyLibrary, Document

    result = await db.execute(select(PolicyLibrary).where(PolicyLibrary.id == library_id))
    lib = result.scalar_one_or_none()
    if not lib:
        raise HTTPException(status_code=404, detail="Policy library not found")

    # Delete associated files from disk
    docs_result = await db.execute(select(Document).where(Document.policy_library_id == library_id))
    docs = docs_result.scalars().all()
    for doc in docs:
        try:
            os.unlink(doc.file_path)
        except FileNotFoundError:
            pass

    await db.delete(lib)
    await db.commit()


# ── Document management ────────────────────────────────────────────────────────

@router.get("/libraries/{library_id}/processing-progress")
async def get_library_processing_progress(
    library_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    """Return ingestion pipeline stage progress for all processing docs in this policy library."""
    from app.models.orm import Document, IngestionRun
    from sqlalchemy import desc
    result = await db.execute(
        select(Document.id).where(Document.policy_library_id == library_id, Document.parse_status == "processing")
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


@router.get("/libraries/{library_id}/documents")
async def list_library_documents(
    library_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> list[dict]:
    from app.models.orm import Document

    result = await db.execute(
        select(Document)
        .where(Document.policy_library_id == library_id)
        .order_by(Document.created_at.desc())
    )
    return [_doc_dict(d) for d in result.scalars().all()]


@router.post("/libraries/{library_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_library_document(
    library_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
) -> dict:
    from app.models.orm import PolicyLibrary, Document

    result = await db.execute(select(PolicyLibrary).where(PolicyLibrary.id == library_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Policy library not found")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type not allowed: {suffix}")

    content = await file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_size_mb}MB limit")

    file_hash = hashlib.sha256(content).hexdigest()
    existing = await db.execute(
        select(Document).where(Document.policy_library_id == library_id, Document.file_hash == file_hash)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="File already uploaded to this library")

    upload_dir = Path(settings.upload_dir) / f"pl_{library_id}"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{uuid.uuid4().hex}{suffix}"
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    doc = Document(
        policy_library_id=library_id,
        project_id=None,
        provider_id=None,
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


@router.post("/libraries/{library_id}/documents/{doc_id}/reparse")
async def reparse_library_document(
    library_id: int,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> dict:
    from app.models.orm import Document

    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.policy_library_id == library_id)
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


@router.post("/libraries/{library_id}/documents/{doc_id}/reindex")
async def reindex_library_document(
    library_id: int,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> dict:
    from app.models.orm import Document

    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.policy_library_id == library_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.parse_status in ("pending", "processing", "indexing", "queued"):
        raise HTTPException(status_code=409, detail="Document is already being processed or queued")
    if doc.parse_status not in ("complete", "indexed", "index_failed", "failed"):
        raise HTTPException(status_code=409, detail="Document must be fully parsed before indexing")

    doc.parse_status = "pending"
    doc.parse_error = None
    await db.commit()

    from app.services.ingestion.pipeline import run_ingestion_pipeline
    asyncio.create_task(run_ingestion_pipeline(document_id=doc.id))
    return _doc_dict(doc)


@router.delete("/libraries/{library_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_library_document(
    library_id: int,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> None:
    from app.models.orm import Document

    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.policy_library_id == library_id)
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


@router.get("/libraries/{library_id}/documents/{doc_id}/download")
async def download_library_document(
    library_id: int,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    from fastapi.responses import FileResponse as FR
    from app.models.orm import Document

    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.policy_library_id == library_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not Path(doc.file_path).exists():
        raise HTTPException(status_code=410, detail="File no longer exists on disk")
    return FR(path=doc.file_path, filename=doc.filename, media_type="application/octet-stream")


@router.get("/libraries/{library_id}/documents/{doc_id}/chunks")
async def get_library_document_chunks(
    library_id: int,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> dict:
    """Return evidence excerpts with control mappings for the Document Explorer."""
    from app.models.orm import Document

    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.policy_library_id == library_id)
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
