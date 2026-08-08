"""Line-level document parser.

Converts a ParsedDocument (from the existing parsers) into a flat list of
line-level dicts. Each dict has full source provenance: document ID, page
number, section heading path, table coordinates if applicable, content type,
and the raw extracted text.

This is Stage 1 of the ingestion pipeline. Its output is the canonical
source representation — all downstream stages reference line numbers
produced here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.parsers.base import ParsedDocument


@dataclass
class LineRecord:
    line_number: int        # 1-based, sequential within document
    page_number: int | None
    section_path: str | None
    block_id: str | None
    block_type: str | None
    table_id: str | None
    row_index: int | None
    col_index: int | None
    cell_label: str | None
    content_type: str       # text | heading | list_item | table_cell | caption | footnote
    content: str


_HEADING_PATTERN = re.compile(
    r'^(?:\d+[\.\d]*\s+|[A-Z]\.\s+|#{1,6}\s+|[IVX]+\.\s+)?'
    r'([A-Z][A-Za-z0-9 &/,\-]{3,80})$'
)
_LIST_ITEM_PATTERN = re.compile(r'^\s*[\u2022\u2023\u25e6\-\*\d+\.]\s+')
_TABLE_SEP_PATTERN = re.compile(r'^\s*[\|\+\-]{3,}')


def _detect_content_type(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return "text"
    if _TABLE_SEP_PATTERN.match(stripped):
        return "text"  # table separator — skip/treat as text
    if "|" in stripped and stripped.count("|") >= 2:
        return "table_cell"
    if _LIST_ITEM_PATTERN.match(stripped):
        return "list_item"
    if _HEADING_PATTERN.match(stripped) and len(stripped) < 120:
        return "heading"
    return "text"


def _update_section_path(current_path: list[str], heading: str) -> list[str]:
    """Maintain a rolling section heading stack."""
    heading = heading.strip()
    if not heading:
        return current_path
    # Simple heuristic: numbered headings reset depth based on level
    depth_match = re.match(r'^(\d+(?:\.\d+)*)\s+', heading)
    if depth_match:
        depth = depth_match.group(1).count(".") + 1  # 1.2.3 → depth 3
        # Truncate path to this depth, then append
        new_path = current_path[:depth - 1] + [heading]
    else:
        # Non-numbered — append at current depth or replace top
        if len(current_path) < 3:
            new_path = current_path + [heading]
        else:
            new_path = current_path[:-1] + [heading]
    return new_path


def _parse_table_line(line: str, row_index: int, table_id: str) -> list[LineRecord]:
    """Split a pipe-delimited table row into individual cell records."""
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    records = []
    for col_idx, cell in enumerate(cells):
        if cell:
            records.append(LineRecord(
                line_number=0,  # assigned by caller
                page_number=None,
                section_path=None,
                block_id=None,
                block_type="table_row",
                table_id=table_id,
                row_index=row_index,
                col_index=col_idx,
                cell_label=None,
                content_type="table_cell",
                content=cell,
            ))
    return records


def extract_lines(parsed: ParsedDocument) -> list[LineRecord]:
    """Extract line-level records from a ParsedDocument.

    Preserves:
    - Page numbers from ParsedPage
    - Section heading hierarchy (rolling stack)
    - Table structure (pipe-delimited rows -> individual cells)
    - Content type classification
    - Sequential line numbering across the whole document
    """
    records: list[LineRecord] = []
    line_number = 1
    section_stack: list[str] = []
    current_table_id: str | None = None
    table_row_index: int = 0
    table_counter: int = 0

    for page in parsed.pages:
        page_num = page.page_number
        if getattr(page, "blocks", None):
            block_records, line_number, section_stack = _extract_from_blocks(
                page,
                line_number=line_number,
                section_stack=section_stack,
            )
            records.extend(block_records)
            current_table_id = None
            table_row_index = 0
            continue
        # Seed section path from page section_title if available
        if page.section_title and page.section_title not in section_stack:
            section_stack = _update_section_path(section_stack, page.section_title)

        raw_lines = page.content.splitlines()
        for raw_line in raw_lines:
            stripped = raw_line.strip()
            if not stripped:
                # Blank line ends a table block
                if current_table_id:
                    current_table_id = None
                    table_row_index = 0
                continue

            ctype = _detect_content_type(stripped)

            if ctype == "heading":
                section_stack = _update_section_path(section_stack, stripped)
                current_table_id = None
                table_row_index = 0
                rec = LineRecord(
                    line_number=line_number,
                    page_number=page_num,
                    section_path=" > ".join(section_stack) if section_stack else None,
                    block_id=None,
                    block_type="heading",
                    table_id=None,
                    row_index=None,
                    col_index=None,
                    cell_label=None,
                    content_type="heading",
                    content=stripped,
                )
                records.append(rec)
                line_number += 1

            elif ctype == "table_cell":
                # Start new table if not already in one
                if current_table_id is None:
                    table_counter += 1
                    current_table_id = f"T{table_counter}_p{page_num}"
                    table_row_index = 0

                cell_records = _parse_table_line(stripped, table_row_index, current_table_id)
                section_path_str = " > ".join(section_stack) if section_stack else None
                for cr in cell_records:
                    cr.line_number = line_number
                    cr.page_number = page_num
                    cr.section_path = section_path_str
                    cr.block_id = f"{current_table_id}-r{table_row_index}"
                    records.append(cr)
                    line_number += 1
                table_row_index += 1

            else:
                current_table_id = None
                table_row_index = 0
                rec = LineRecord(
                    line_number=line_number,
                    page_number=page_num,
                    section_path=" > ".join(section_stack) if section_stack else None,
                    block_id=None,
                    block_type=ctype,
                    table_id=None,
                    row_index=None,
                    col_index=None,
                    cell_label=None,
                    content_type=ctype,
                    content=stripped,
                )
                records.append(rec)
                line_number += 1

    return records


def _extract_from_blocks(
    page,
    line_number: int,
    section_stack: list[str],
) -> tuple[list[LineRecord], int, list[str]]:
    """Convert structured parser blocks into canonical line records."""
    records: list[LineRecord] = []
    page_num = page.page_number

    if page.section_title and page.section_title not in section_stack:
        section_stack = _update_section_path(section_stack, page.section_title)

    for block in page.blocks:
        block_text = (block.text or "").strip()
        if not block_text and not getattr(block, "cells", None):
            continue

        heading_path = list(getattr(block, "heading_path", []) or [])
        if heading_path:
            section_stack = heading_path
        section_path = " > ".join(section_stack) if section_stack else None
        block_id = getattr(block, "block_id", None)
        block_type = getattr(block, "block_type", None)
        cells = getattr(block, "cells", []) or []

        if block_type == "heading" and block_text:
            section_stack = _update_section_path(section_stack, block_text)
            section_path = " > ".join(section_stack) if section_stack else None

        if cells:
            for cell in cells:
                if not cell.text:
                    continue
                records.append(
                    LineRecord(
                        line_number=line_number,
                        page_number=page_num,
                        section_path=section_path,
                        block_id=block_id,
                        block_type=block_type,
                        table_id=getattr(block, "table_id", None),
                        row_index=cell.row_index,
                        col_index=cell.col_index,
                        cell_label=cell.header,
                        content_type="table_cell",
                        content=cell.text.strip(),
                    )
                )
                line_number += 1
            continue

        for raw_line in block_text.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            content_type = {
                "heading": "heading",
                "list_item": "list_item",
                "table_row": "text",
                "paragraph": "text",
                "caption": "caption",
                "footnote": "footnote",
            }.get(block_type or "", _detect_content_type(stripped))
            records.append(
                LineRecord(
                    line_number=line_number,
                    page_number=page_num,
                    section_path=section_path,
                    block_id=block_id,
                    block_type=block_type,
                    table_id=getattr(block, "table_id", None),
                    row_index=getattr(block, "row_index", None),
                    col_index=getattr(block, "col_index", None),
                    cell_label=getattr(block, "cell_label", None),
                    content_type=content_type,
                    content=stripped,
                )
            )
            line_number += 1

    return records, line_number, section_stack
