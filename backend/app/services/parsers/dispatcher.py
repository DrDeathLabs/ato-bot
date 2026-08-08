"""Document parser dispatcher — routes to correct parser by file type."""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.services.parsers.base import ParsedDocument


IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".tiff", ".bmp"}


def parse_document(file_path: str) -> ParsedDocument:
    """Parse a document file and return ParsedDocument."""
    suffix = Path(file_path).suffix.lower()

    if suffix == ".pdf":
        from app.services.parsers.pdf_parser import parse_pdf
        return parse_pdf(file_path)
    elif suffix in (".docx", ".doc"):
        from app.services.parsers.docx_parser import parse_docx
        return parse_docx(file_path)
    elif suffix in (".xlsx", ".xls"):
        from app.services.parsers.xlsx_parser import parse_xlsx
        return parse_xlsx(file_path)
    elif suffix in (".pptx", ".ppt"):
        from app.services.parsers.pptx_parser import parse_pptx
        return parse_pptx(file_path)
    elif suffix in (".vsdx", ".vsd"):
        from app.services.parsers.visio_parser import parse_visio
        return parse_visio(file_path)
    elif suffix in IMAGE_TYPES:
        from app.services.parsers.image_parser import parse_image
        return parse_image(file_path)
    elif suffix in (".txt", ".md", ".rst", ".text"):
        from app.services.parsers.text_parser import parse_text
        return parse_text(file_path)
    else:
        # Attempt plain text fallback
        from app.services.parsers.text_parser import parse_text
        return parse_text(file_path)


async def dispatch_parse(document_id: int) -> None:
    """Background task: run the full v2 ingestion pipeline for a document.

    Replaces the legacy parse → chunk → tag flow with the staged pipeline:
      parse → screen → expand → classify → embed → legacy-chunk-backfill
    """
    import logging
    _logger = logging.getLogger(__name__)
    try:
        from app.services.ingestion.pipeline import run_ingestion_pipeline
        await run_ingestion_pipeline(document_id=document_id)
    except Exception as exc:
        _logger.error("dispatch_parse failed for document %d: %s", document_id, exc, exc_info=True)
        # Mark document failed so the UI shows an actionable status
        try:
            from app.core.database import AsyncSessionLocal
            from sqlalchemy import select as _sel
            from app.models.orm import Document as _Doc
            async with AsyncSessionLocal() as db:
                res = await db.execute(_sel(_Doc).where(_Doc.id == document_id))
                doc = res.scalar_one_or_none()
                if doc and doc.parse_status not in ("indexed", "complete"):
                    doc.parse_status = "failed"
                    doc.parse_error = f"Pipeline error: {type(exc).__name__}: {str(exc)[:200]}"
                    await db.commit()
        except Exception:
            pass


async def dispatch_parse_batch(document_ids: list[int], max_concurrency: int = 4) -> None:
    """Run staged ingestion for multiple documents with bounded concurrency."""
    unique_ids = [doc_id for doc_id in dict.fromkeys(document_ids) if doc_id]
    if not unique_ids:
        return

    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _run(document_id: int) -> None:
        async with semaphore:
            await dispatch_parse(document_id)

    await asyncio.gather(*(_run(document_id) for document_id in unique_ids))


async def dispatch_parse_and_categorize(document_id: int) -> None:
    """Categorize a procedure document, then run the staged ingestion pipeline."""
    import logging
    _logger = logging.getLogger(__name__)
    try:
        from app.services.procedure_categorizer import categorize_and_tag
        await categorize_and_tag(document_id)
    except Exception as exc:
        _logger.error("dispatch_parse_and_categorize failed for document %d: %s", document_id, exc, exc_info=True)
        try:
            from app.core.database import AsyncSessionLocal
            from sqlalchemy import select as _sel
            from app.models.orm import Document as _Doc
            async with AsyncSessionLocal() as db:
                res = await db.execute(_sel(_Doc).where(_Doc.id == document_id))
                doc = res.scalar_one_or_none()
                if doc and doc.parse_status not in ("indexed", "complete"):
                    doc.parse_status = "failed"
                    doc.parse_error = f"Procedure pipeline error: {type(exc).__name__}: {str(exc)[:200]}"
                    await db.commit()
        except Exception:
            pass


async def _trigger_categorize_and_tag(document_id: int) -> None:
    """Chain: LLM categorize → assign library → tag NIST controls."""
    from app.services.procedure_categorizer import categorize_and_tag
    await categorize_and_tag(document_id)
