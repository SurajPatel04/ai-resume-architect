import logging
from typing import Optional

from langchain_community.document_loaders import PyMuPDFLoader

logger = logging.getLogger(__name__)

def parse_pdf(file_path: str) -> Optional[str]:
    """
    Parses a PDF file and extracts its text content using PyMuPDFLoader.
    
    Args:
        file_path: The absolute or relative path to the PDF file.
        
    Returns:
        The extracted text as a single string, or None if an error occurs.
    """
    try:
        loader = PyMuPDFLoader(file_path)
        documents = loader.load()
        
        if len(documents) > 4:
            raise ValueError("The provided PDF has more than 4 pages and is likely not a resume.")
            
        full_text = "\n\n".join([doc.page_content for doc in documents])
        return full_text
    
    except Exception as e:
        logger.error(f"Error parsing PDF at {file_path}: {e}")
        return None
