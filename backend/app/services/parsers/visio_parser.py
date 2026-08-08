"""Visio (.vsdx) parser using vsdx."""
from __future__ import annotations

from pathlib import Path

from app.services.parsers.base import ParsedDocument, ParsedPage


def parse_visio(file_path: str) -> ParsedDocument:
    try:
        import vsdx
    except ImportError:
        return ParsedDocument(filename=Path(file_path).name, file_type="vsdx",
                              error="python-vsdx not installed")

    doc = ParsedDocument(filename=Path(file_path).name, file_type="vsdx")
    try:
        with vsdx.VisioFile(file_path) as vis:
            pages = []
            for page_idx, page in enumerate(vis.pages, start=1):
                shape_texts = []
                for shape in page.child_shapes:
                    text = shape.text
                    if text and text.strip():
                        shape_texts.append(text.strip())
                    # Recurse into sub-shapes
                    for sub in shape.child_shapes:
                        sub_text = sub.text
                        if sub_text and sub_text.strip():
                            shape_texts.append(sub_text.strip())

                if shape_texts:
                    content = "\n".join(shape_texts)
                    pages.append(ParsedPage(
                        page_number=page_idx,
                        content=content,
                        section_title=page.name or f"Page {page_idx}",
                    ))
            doc.pages = pages
            doc.full_text = "\n\n".join(
                f"[Diagram: {p.section_title}]\n{p.content}" for p in pages
            )
    except Exception as e:
        doc.error = str(e)
    return doc
