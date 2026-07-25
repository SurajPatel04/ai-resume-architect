import logging
from typing import Any, Dict, List
from app.graphs.state import ResumeState
from app.utils.llm import get_openai_llm
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class ExtractedEntity(BaseModel):
    field: str = Field(description="The exact field name from the requested fields.")
    value: Any = Field(description="The extracted value.")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0. Use lower scores (e.g. 0.5) if the user's answer is ambiguous or might contain a typo.")

class ExtractionResult(BaseModel):
    is_skip: bool = Field(description="True if the user explicitly skipped, declined, or indicated they don't have this information (e.g. 'No', 'I don't have any').")
    entities: List[ExtractedEntity] = Field(default_factory=list, description="A list of extracted entities. Omit fields they didn't answer.")

def extract_entities(state: ResumeState) -> Dict[str, Any]:
    """
    Extracts data from the user's latest answer using an LLM.
    Returns the raw extracted entities (or skip status) to be processed by validate_entities.
    """
    logger.info("Extracting entities from user input...")
    latest_answer = state.get("latest_answer")
    current_question = state.get("current_question")
    
    if not latest_answer or not current_question:
        return {"extracted_entities": {"is_skip": False, "entities": []}}

    target_field = current_question.get("field")
    section_name = current_question.get("section")
    missing_fields = current_question.get("missing_fields", [])
    
    if not target_field:
        return {"extracted_entities": {"is_skip": False, "entities": []}}

    llm = get_openai_llm()
    structured_llm = llm.with_structured_output(ExtractionResult, method="function_calling")

    prompt = f"""
    The user was asked to provide information for their resume.
    Section: {section_name}
    Target Item: {target_field}
    Requested Fields: {missing_fields}
    Question Asked: {current_question.get('question_text')}
    User's Answer: {latest_answer}

    Determine if the user provided the information or if they explicitly skipped/declined.
    If they provided information, extract each provided field into the `entities` list with a confidence score.
    CRITICAL INSTRUCTION: Only include entities that the user ACTUALLY answered. If the user provided 2 out of 3 requested fields, the 3rd field MUST be omitted entirely.
    """

    try:
        result: ExtractionResult = structured_llm.invoke(prompt)
        logger.info(f"Extraction result - is_skip: {result.is_skip}, entities: {[e.field for e in result.entities]}")
        
        return {
            "extracted_entities": {
                "is_skip": result.is_skip,
                "entities": [e.model_dump() for e in result.entities]
            }
        }
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        return {"extracted_entities": {"is_skip": False, "entities": []}}
