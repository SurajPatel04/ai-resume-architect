import logging
from typing import Optional

import pymupdf

logger = logging.getLogger(__name__)

MAX_PAGES = 4

def parse_pdf(file_path: str) -> Optional[str]:
    """
    Parses a PDF file and extracts its text content.

    Args:
        file_path: The absolute or relative path to the PDF file.

    Returns:
        The extracted text as a single string, or None if an error occurs.
    """
    try:
        with pymupdf.open(file_path) as doc:
            if doc.page_count > MAX_PAGES:
                raise ValueError(
                    f"The provided PDF has {doc.page_count} pages and is likely not a resume."
                )

            return "\n\n".join(page.get_text() for page in doc)

    except Exception as e:
        logger.error(f"Error parsing PDF at {file_path}: {e}")
        return None