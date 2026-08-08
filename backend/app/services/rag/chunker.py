"""Semantic document chunker — splits ParsedDocument into retrievable chunks."""
from __future__ import annotations

from dataclasses import dataclass

import tiktoken

from app.services.parsers.base import ParsedDocument

try:
    _enc = tiktoken.get_encoding("cl100k_base")
except Exception:
    _enc = None


def count_tokens(text: str) -> int:
    if _enc:
        return len(_enc.encode(text))
    return len(text) // 4  # rough fallback


@dataclass
class Chunk:
    content: str
    section_title: str | None
    page_number: int | None
    token_count: int
    document_filename: str = ""


def chunk_parsed_document(
    parsed: ParsedDocument,
    max_tokens: int = 512,
    overlap_tokens: int = 64,
) -> list[Chunk]:
    """Split parsed document into overlapping chunks of ~max_tokens each."""
    chunks: list[Chunk] = []

    for page in parsed.pages:
        if not page.content.strip():
            continue
        page_chunks = _chunk_text(
            page.content,
            section_title=page.section_title,
            page_number=page.page_number,
            filename=parsed.filename,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )
        chunks.extend(page_chunks)

    return chunks


def _chunk_text(
    text: str,
    section_title: str | None,
    page_number: int | None,
    filename: str,
    max_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    """Split text into overlapping token-bounded chunks."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[Chunk] = []
    current_paras: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = count_tokens(para)
        if para_tokens > max_tokens:
            # Para too large — split by sentences
            if current_paras:
                chunks.append(_make_chunk(current_paras, section_title, page_number, filename))
                # Keep overlap
                current_paras = current_paras[-1:] if current_paras else []
                current_tokens = count_tokens(" ".join(current_paras))
            for sent_chunk in _split_large_para(para, max_tokens, overlap_tokens):
                chunks.append(Chunk(
                    content=sent_chunk,
                    section_title=section_title,
                    page_number=page_number,
                    token_count=count_tokens(sent_chunk),
                    document_filename=filename,
                ))
            continue

        if current_tokens + para_tokens > max_tokens and current_paras:
            chunks.append(_make_chunk(current_paras, section_title, page_number, filename))
            # Overlap: keep last paragraph
            overlap_paras = current_paras[-1:] if current_paras else []
            current_paras = overlap_paras + [para]
            current_tokens = count_tokens(" ".join(current_paras))
        else:
            current_paras.append(para)
            current_tokens += para_tokens

    if current_paras:
        chunks.append(_make_chunk(current_paras, section_title, page_number, filename))

    return chunks


def _make_chunk(paras: list[str], section_title, page_number, filename) -> Chunk:
    content = "\n\n".join(paras)
    return Chunk(
        content=content,
        section_title=section_title,
        page_number=page_number,
        token_count=count_tokens(content),
        document_filename=filename,
    )


def _split_large_para(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    """Split a large paragraph into sentence-level chunks."""
    import re
    sentences = re.split(r"(?<=[.!?])\s+", text)
    result: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for sent in sentences:
        sent_tokens = count_tokens(sent)
        if current_tokens + sent_tokens > max_tokens and current:
            result.append(" ".join(current))
            current = current[-2:] if len(current) > 2 else current
            current_tokens = count_tokens(" ".join(current))
        current.append(sent)
        current_tokens += sent_tokens

    if current:
        result.append(" ".join(current))
    return result
