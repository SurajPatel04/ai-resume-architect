import logging
from typing import Any, Dict, Optional
from app.graphs.state import ResumeState
from app.utils.llm import get_openai_llm
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class VerificationResult(BaseModel):
    is_correct: bool = Field(description="True if the user confirmed the value is correct.")
    corrected_value: Optional[str] = Field(description="The corrected value if the user provided one.")

def process_verification(state: ResumeState) -> Dict[str, Any]:
    """
    Processes the user's answer to a verification question.
    Updates the entity's confidence to 1.0, applies corrections, and clears latest_answer.
    """
    logger.info("Processing user verification answer...")
    latest_answer = state.get("latest_answer")
    current_question = state.get("current_question", {})
    verifying_field = current_question.get("verifying_field")
    
    extracted = state.get("extracted_entities", {})
                                                                                    
    if "items" in extracted:
        item_index = current_question.get("verifying_item", 0)
        items = list(extracted.get("items") or [])
        if not isinstance(item_index, int) or item_index < 0 or item_index >= len(items)\
                or verifying_field not in items[item_index]:
            logger.warning("Could not find typed field %r on item %r.", verifying_field, item_index)
            return {"latest_answer": None}

        item = dict(items[item_index])
        value = item[verifying_field]
        result = None
        try:
            prompt = f"""
            The user was asked to verify the extracted value '{value}' for the field '{verifying_field}'.
            User's answer: "{latest_answer}"

            Did the user confirm the value is correct? If they provided a correction, extract it.
            """
            result = get_openai_llm().with_structured_output(VerificationResult).invoke(prompt)
            if not result.is_correct and result.corrected_value:
                item[verifying_field] = result.corrected_value
        except Exception as e:
            logger.error("Failed to process typed verification: %s", e)

        items[item_index] = item
        extracted["items"] = items
        extracted["confidence"] = [
            c for c in extracted.get("confidence") or []
            if not (c.get("item", 0) == item_index and c.get("field") == verifying_field)
        ]
        return {"extracted_entities": extracted, "latest_answer": None}

    entities = extracted.get("entities", [])
    
    entity_idx = -1
    entity = None
    for i, e in enumerate(entities):
        if e["field"] == verifying_field:
            entity_idx = i
            entity = e
            break
            
    if not entity:
        logger.warning(f"Could not find verifying_field '{verifying_field}' in extracted entities.")
        return {"latest_answer": None}
        
    llm = get_openai_llm()
    structured = llm.with_structured_output(VerificationResult)
    
    prompt = f"""
    The user was asked to verify the extracted value '{entity['value']}' for the field '{verifying_field}'.
    User's answer: "{latest_answer}"
    
    Did the user confirm the value is correct?
    If they provided a correction, extract the corrected value.
    """
    
    try:
        result = structured.invoke(prompt)
        
        if result.is_correct:
            logger.info(f"User confirmed '{verifying_field}' is correct.")
            entity["confidence"] = 1.0
        elif result.corrected_value:
            logger.info(f"User corrected '{verifying_field}' to '{result.corrected_value}'.")
            entity["value"] = result.corrected_value
            entity["confidence"] = 1.0
        else:
            logger.info(f"User did not provide a clear correction. Keeping original value and setting confidence to 1.0.")
            entity["confidence"] = 1.0 
            
        entities[entity_idx] = entity
        extracted["entities"] = entities
        
    except Exception as e:
        logger.error(f"Failed to process verification: {e}")
                                                                                         
        entity["confidence"] = 1.0
        entities[entity_idx] = entity
        extracted["entities"] = entities
        
    return {"extracted_entities": extracted, "latest_answer": None}
