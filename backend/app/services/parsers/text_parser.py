"""Plain text and Markdown parser."""
from __future__ import annotations

from pathlib import Path

from app.services.parsers.base import ParsedDocument, ParsedPage


def parse_text(file_path: str) -> ParsedDocument:
    doc = ParsedDocument(filename=Path(file_path).name, file_type="text")
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        doc.full_text = content
        # Split into pseudo-pages by section headers (## or ===)
        sections = _split_sections(content)
        doc.pages = [
            ParsedPage(page_number=i + 1, content=text, section_title=title)
            for i, (title, text) in enumerate(sections)
        ]
    except Exception as e:
        doc.error = str(e)
    return doc


def _split_sections(text: str) -> list[tuple[str | None, str]]:
    """Split markdown/text into sections by headings."""
    import re
    heading_re = re.compile(r"^(#{1,3}|={3,}|-{3,})\s*(.+)", re.MULTILINE)
    sections = []
    last_pos = 0
    last_title: str | None = None

    for match in heading_re.finditer(text):
        if match.start() > last_pos:
            sections.append((last_title, text[last_pos:match.start()].strip()))
        last_title = match.group(2).strip()
        last_pos = match.end()

    if last_pos < len(text):
        sections.append((last_title, text[last_pos:].strip()))

    # If no headings found, return whole text as single section
    if not sections:
        return [(None, text)]

    return [(t, c) for t, c in sections if c]
