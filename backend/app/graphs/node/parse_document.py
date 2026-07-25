import logging
from typing import Any, Dict

from app.graphs.state import Resume, ResumeState
from app.utils.llm import get_openai_llm
from app.utils.pdf_parser import parse_pdf

logger = logging.getLogger(__name__)

def parse_document(state: ResumeState) -> Dict[str, Any]:
    """
    Node that parses an uploaded document (PDF) and uses an LLM with structured output
    to populate the initial master_profile state.
    """
    uploaded_file = state.get("uploaded_file")
    uploaded_text = state.get("uploaded_text")

    # If no text provided, try parsing the PDF file using pdf_parser
    if not uploaded_text and uploaded_file:
        logger.info(f"Parsing PDF document from file path: {uploaded_file}")
        uploaded_text = parse_pdf(uploaded_file)
        
    if not uploaded_text:
        logger.warning("No uploaded text or file available to parse.")
        return {}

    # Initialize LLM with structured output bound to the Resume Pydantic model
    llm = get_openai_llm()
    structured_llm = llm.with_structured_output(Resume)

    prompt = f"""
    You are an expert resume parser. Extract structured information from the following raw resume text.
    Ensure accuracy and organize contact information, work experience, education, skills, and projects carefully.

    Raw Resume Text:
    ---
    {uploaded_text}
    ---
    """

    try:
        parsed_profile=structured_llm.invoke(prompt)
        logger.info("Successfully parsed document into structured Resume format.")
        print("parssed_profile: ", parsed_profile)
        return {
            "master_profile": parsed_profile,
            "uploaded_text": uploaded_text
        }
    except Exception as e:
        logger.error(f"Error during structured LLM parsing: {e}")
        return {
            "validation_errors": [f"Failed to parse document: {str(e)}"]
        }
