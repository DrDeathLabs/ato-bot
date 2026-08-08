"""Image parser — OCR via pytesseract, with Claude vision fallback."""
from __future__ import annotations

from pathlib import Path

from app.services.parsers.base import ParsedDocument, ParsedPage


def parse_image(file_path: str, use_claude_vision: bool = False) -> ParsedDocument:
    doc = ParsedDocument(filename=Path(file_path).name, file_type="image")
    try:
        if use_claude_vision:
            text = _claude_vision(file_path)
        else:
            text = _tesseract_ocr(file_path)

        if text.strip():
            doc.pages = [ParsedPage(page_number=1, content=text.strip())]
            doc.full_text = text.strip()
        else:
            doc.error = "No text extracted from image"
    except Exception as e:
        doc.error = str(e)
    return doc


def _tesseract_ocr(file_path: str) -> str:
    from PIL import Image
    import pytesseract
    img = Image.open(file_path)
    return pytesseract.image_to_string(img)


def _claude_vision(file_path: str) -> str:
    """Use Claude claude-sonnet-4-6 vision to extract text/description from image."""
    import base64
    import anthropic
    from app.core.config import get_settings
    settings = get_settings()

    with open(file_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode()

    suffix = Path(file_path).suffix.lower()
    media_type_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                      ".gif": "image/gif", ".tiff": "image/tiff", ".bmp": "image/bmp"}
    media_type = media_type_map.get(suffix, "image/png")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.claude_model,
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": image_data},
                },
                {
                    "type": "text",
                    "text": ("Extract all text visible in this image. "
                             "If this is a diagram or architecture drawing, describe the components, "
                             "connections, security controls, and data flows shown. "
                             "Focus on information relevant to security controls and system architecture."),
                },
            ],
        }],
    )
    return message.content[0].text
