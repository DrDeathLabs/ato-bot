"""pgvector-based semantic retriever over evidence-unit embeddings."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Document
from app.services.ingestion.embedding_provider import accepted_model_names
from app.services.rag.embedder import embed_text_active

logger = logging.getLogger(__name__)

_INDEXED = ("indexed", "complete")


def _download_url_for_doc(project_id: int, doc: dict[str, Any]) -> str | None:
    if doc.get("project_id") == project_id:
        return f"/projects/{project_id}/documents/{doc['document_id']}/download"
    if doc.get("provider_id") is not None:
        return f"/common-controls/providers/{doc['provider_id']}/documents/{doc['document_id']}/download"
    if doc.get("policy_library_id") is not None:
        return f"/enterprise-policies/libraries/{doc['policy_library_id']}/documents/{doc['document_id']}/download"
    if doc.get("procedure_library_id") is not None:
        return f"/enterprise-procedures/libraries/{doc['procedure_library_id']}/documents/{doc['document_id']}/download"
    return None


def _to_chunk_dict(project_id: int, row: tuple[Any, ...]) -> dict[str, Any]:
    (
        content,
        section_path,
        document_id,
        filename,
        document_type,
        document_intent,
        created_at,
        doc_project_id,
        provider_id,
        policy_library_id,
        procedure_library_id,
    ) = row

    meta = {
        "document_id": document_id,
        "project_id": doc_project_id,
        "provider_id": provider_id,
        "policy_library_id": policy_library_id,
        "procedure_library_id": procedure_library_id,
    }
    if provider_id is not None:
        source_type = "common_control"
    elif policy_library_id is not None:
        source_type = "policy"
    elif procedure_library_id is not None:
        source_type = "procedure"
    else:
        source_type = "project"

    return {
        "content": content,
        "section_path": section_path or "",
        "filename": filename or "Unknown",
        "document_type": document_type or "other",
        "document_intent": document_intent or "other",
        "date": created_at.strftime("%Y-%m-%d") if created_at else None,
        "source_type": source_type,
        "document_id": document_id,
        "download_url": _download_url_for_doc(project_id, meta),
    }


async def retrieve_chunks(
    query: str,
    project_id: int,
    db: AsyncSession,
    top_k: int = 8,
    embedding_provider: str = "voyage",
    max_tokens: int = 4096,
    extra_doc_ids: list[int] | None = None,
    allowed_doc_ids: list[int] | None = None,
    allowed_run_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Retrieve top-K evidence excerpts with source metadata."""
    if allowed_doc_ids is not None:
        doc_ids = list(dict.fromkeys(allowed_doc_ids))
    else:
        doc_result = await db.execute(
            select(Document.id).where(
                Document.project_id == project_id,
                Document.parse_status.in_(_INDEXED),
            )
        )
        doc_ids = [row[0] for row in doc_result.fetchall()]
        if extra_doc_ids:
            doc_ids = list(set(doc_ids) | set(extra_doc_ids))
    if not doc_ids:
        return []

    try:
        query_embedding, embedding_meta = await embed_text_active(query)
    except Exception:
        return []

    if len(query_embedding) != 1024:
        return []

    embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"
    accepted_models = accepted_model_names(embedding_meta["provider"], embedding_meta["model"])
    return await _search_evidence_embeddings(
        project_id, db, doc_ids, embedding_str, top_k, max_tokens, accepted_models, allowed_run_ids
    )


async def retrieve_chunks_multi_query(
    queries: list[str],
    project_id: int,
    db: AsyncSession,
    top_k_per_query: int = 4,
    embedding_provider: str = "voyage",
    max_tokens: int = 4096,
    extra_doc_ids: list[int] | None = None,
    allowed_doc_ids: list[int] | None = None,
    allowed_run_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Run multiple evidence searches and merge structured results."""
    if not queries:
        return []

    if allowed_doc_ids is not None:
        doc_ids = list(dict.fromkeys(allowed_doc_ids))
    else:
        doc_result = await db.execute(
            select(Document.id).where(
                Document.project_id == project_id,
                Document.parse_status.in_(_INDEXED),
            )
        )
        doc_ids = [row[0] for row in doc_result.fetchall()]
        if extra_doc_ids:
            doc_ids = list(set(doc_ids) | set(extra_doc_ids))
    if not doc_ids:
        return []

    embedding_results = await asyncio.gather(
        *[embed_text_active(query) for query in queries],
        return_exceptions=True,
    )

    seen: set[tuple[Any, str]] = set()
    merged: list[dict[str, Any]] = []
    total_tokens = 0

    for embedding_result in embedding_results:
        if isinstance(embedding_result, Exception):
            continue
        embedding, embedding_meta = embedding_result
        if len(embedding) != 1024:
            continue

        embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
        accepted_models = accepted_model_names(embedding_meta["provider"], embedding_meta["model"])
        rows = await _raw_evidence_search(
            project_id, db, doc_ids, embedding_str, top_k_per_query, accepted_models, allowed_run_ids
        )

        for row in rows:
            identity = (row["document_id"], row["content"])
            if identity in seen:
                continue
            seen.add(identity)
            chunk_tokens = len((row.get("content") or "")) // 4
            if total_tokens + chunk_tokens > max_tokens:
                continue
            merged.append(row)
            total_tokens += chunk_tokens

    return merged


async def _search_evidence_embeddings(
    project_id: int,
    db: AsyncSession,
    doc_ids: list[int],
    embedding_str: str,
    top_k: int,
    max_tokens: int,
    accepted_models: list[str],
    allowed_run_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    rows = await _raw_evidence_search(
        project_id, db, doc_ids, embedding_str, top_k, accepted_models, allowed_run_ids
    )
    chunks: list[dict[str, Any]] = []
    total_tokens = 0
    for row in rows:
        chunk_tokens = len((row.get("content") or "")) // 4
        if total_tokens + chunk_tokens > max_tokens:
            break
        chunks.append(row)
        total_tokens += chunk_tokens
    return chunks


async def _raw_evidence_search(
    project_id: int,
    db: AsyncSession,
    doc_ids: list[int],
    embedding_str: str,
    top_k: int,
    accepted_models: list[str],
    allowed_run_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Search evidence embeddings and return structured evidence rows."""
    try:
        run_filter = "AND eu.run_id = ANY(:run_ids)" if allowed_run_ids else ""
        stmt = text(f"""
            SELECT
                eu.content,
                eu.section_path,
                d.id AS document_id,
                d.filename,
                d.document_type,
                d.document_intent,
                d.created_at,
                d.project_id,
                d.provider_id,
                d.policy_library_id,
                d.procedure_library_id
            FROM evidence_embeddings ee
            JOIN evidence_units eu ON eu.id = ee.unit_id
            JOIN documents d ON d.id = eu.document_id
            WHERE eu.document_id = ANY(:doc_ids)
              AND ee.embedding IS NOT NULL
              AND ee.model_name = ANY(:accepted_models)
              {run_filter}
            ORDER BY ee.embedding <=> '{embedding_str}'::vector, ee.id ASC
            LIMIT :top_k
        """)
        result = await db.execute(
            stmt,
            {
                "doc_ids": doc_ids,
                "top_k": top_k,
                "accepted_models": accepted_models,
                **({"run_ids": allowed_run_ids} if allowed_run_ids else {}),
            },
        )
        return [_to_chunk_dict(project_id, row) for row in result.fetchall()]
    except Exception as exc:
        logger.debug("evidence search failed: %s", exc)
        return []
