"""PDF parser using PyMuPDF (fitz)."""
from __future__ import annotations

from pathlib import Path

from app.services.parsers.base import ParsedBlock, ParsedDocument, ParsedPage


def parse_pdf(file_path: str) -> ParsedDocument:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ParsedDocument(filename=Path(file_path).name, file_type="pdf",
                              error="pymupdf not installed")

    doc = ParsedDocument(
        filename=Path(file_path).name,
        file_type="pdf",
        parser_name="pymupdf",
        parser_version="page-blocks-v1",
    )
    try:
        pdf = fitz.open(file_path)
        doc.metadata = {
            "title": pdf.metadata.get("title", ""),
            "author": pdf.metadata.get("author", ""),
            "page_count": pdf.page_count,
        }
        all_text = []
        for page_num, page in enumerate(pdf, start=1):
            text = page.get_text("text")
            if not text.strip() and page.get_images():
                # Attempt OCR on image-heavy pages
                text = _ocr_page(page)
            section_title = _detect_section(text)
            parsed_page = ParsedPage(
                page_number=page_num,
                content=text.strip(),
                section_title=section_title,
                metadata={"ocr_used": not bool(page.get_text("text").strip()) and bool(text.strip())},
            )
            parsed_page.blocks = _build_blocks_for_page(page_num, text, section_title)
            doc.pages.append(parsed_page)
            all_text.append(text)
        doc.full_text = "\n\n".join(all_text)
        pdf.close()
    except Exception as e:
        doc.error = str(e)
    return doc


def _ocr_page(page) -> str:
    """OCR fallback for scanned PDF pages."""
    try:
        import fitz
        from PIL import Image
        import pytesseract
        import io

        mat = fitz.Matrix(2, 2)  # 2x scale for better OCR
        clip = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(clip.tobytes("png")))
        return pytesseract.image_to_string(img)
    except Exception:
        return ""


def _detect_section(text: str) -> str | None:
    """Heuristic: first non-empty line that looks like a heading."""
    for line in text.splitlines():
        line = line.strip()
        if line and len(line) < 120 and line[0].isupper() and not line.endswith("."):
            return line
    return None


def _build_blocks_for_page(page_num: int, text: str, section_title: str | None) -> list[ParsedBlock]:
    """Preserve rough page-local paragraph structure for downstream provenance."""
    heading_path = [section_title] if section_title else []
    blocks: list[ParsedBlock] = []
    block_counter = 0
    for raw_block in text.split("\n\n"):
        block_text = "\n".join(line.strip() for line in raw_block.splitlines() if line.strip()).strip()
        if not block_text:
            continue
        first_line = block_text.splitlines()[0]
        block_type = "heading" if first_line == section_title else "paragraph"
        block_counter += 1
        blocks.append(
            ParsedBlock(
                block_id=f"pdf-p{page_num}-b{block_counter}",
                block_type=block_type,
                text=block_text,
                heading_path=list(heading_path),
                metadata={"page_number": page_num},
            )
        )
    return blocks
