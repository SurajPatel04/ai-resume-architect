"""Reading a page as a picture rather than as text."""

import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)

RENDER_DPI = 90

def page_as_png(pdf_path: str, page: int = 0) -> Optional[bytes]:
    """One page of a PDF as a PNG, or None if it cannot be rendered."""
    try:
        import pymupdf

        with pymupdf.open(pdf_path) as doc:
            if page >= doc.page_count:
                return None
            return doc[page].get_pixmap(dpi=RENDER_DPI).tobytes("png")
    except Exception as e:
        logger.warning("Could not render %s as an image: %r", pdf_path, e)
        return None

def image_message(png: bytes, prompt: str, detail: str = "high") -> list:

    encoded = base64.b64encode(png).decode("ascii")
    return [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}", "detail": detail},
            },
        ],
    }]
