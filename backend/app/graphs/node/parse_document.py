import json
import logging
from typing import Any, Dict

from app.graphs.rxresume import from_rxresume, looks_like_rxresume
from app.graphs.prompts import PARSE_DOCUMENT
from app.graphs.state import Resume, ResumeState
from app.utils.llm import get_openai_llm
from app.utils.pdf_parser import parse_pdf

logger = logging.getLogger(__name__)

def parse_document(state: ResumeState) -> Dict[str, Any]:
    """Node that parses an uploaded document (PDF) and uses an LLM with structured output to
    populate the initial master_profile state.
    """
    uploaded_file = state.get("uploaded_file")
    uploaded_text = state.get("uploaded_text")

    # source_pdf outlives the parse; choose_style reads the layout off it later.
    consumed: Dict[str, Any] = {"uploaded_text": None, "uploaded_file": None}
    if uploaded_file:
        consumed["source_pdf"] = uploaded_file

    if not uploaded_text and uploaded_file:
        logger.info(f"Parsing PDF document from file path: {uploaded_file}")
        uploaded_text = parse_pdf(uploaded_file)

    if not uploaded_text:
        logger.warning("No uploaded text or file available to parse.")
        return consumed

    try:
        doc = json.loads(uploaded_text)
        if looks_like_rxresume(doc):
            logger.info("Input is an RxResume document; importing directly.")
            return {"master_profile": from_rxresume(doc).model_dump(), **consumed}
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    llm = get_openai_llm()
    structured_llm = llm.with_structured_output(Resume)

    try:
        parsed_profile = structured_llm.invoke(PARSE_DOCUMENT.format(text=uploaded_text))
        logger.info("Successfully parsed document into structured Resume format.")
        # Dumped: structured output returns a live model, and state is checkpointed.
        return {"master_profile": parsed_profile.model_dump(), **consumed}
    except Exception as e:

        logger.error(f"Error during structured LLM parsing: {e}")
        return consumed