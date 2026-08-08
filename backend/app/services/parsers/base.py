"""Base types for document parsing."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedCell:
    """One native cell inside a parsed table row."""

    text: str
    row_index: int
    col_index: int
    header: str | None = None


@dataclass
class ParsedBlock:
    """A logical source block preserved by the parser."""

    block_id: str
    block_type: str
    text: str
    heading_path: list[str] = field(default_factory=list)
    row_index: int | None = None
    col_index: int | None = None
    table_id: str | None = None
    cell_label: str | None = None
    cells: list[ParsedCell] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedPage:
    page_number: int
    content: str
    section_title: str | None = None
    blocks: list[ParsedBlock] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedDocument:
    filename: str
    file_type: str
    pages: list[ParsedPage] = field(default_factory=list)
    full_text: str = ""
    metadata: dict = field(default_factory=dict)
    parser_name: str | None = None
    parser_version: str | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None and bool(self.full_text or self.pages)
