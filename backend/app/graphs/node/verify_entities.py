import logging
from typing import Any, Dict
from app.graphs.state import ResumeState

logger = logging.getLogger(__name__)

def verify_entities(state: ResumeState) -> Dict[str, Any]:
    """
    Checks the confidence of extracted entities.
    If any confidence is below 0.8, generates a verification question and pauses the graph.
    If all are >= 0.8, converts entities to extracted_values for downstream validation.
    """
    logger.info("Verifying extracted entities confidence...")
    extracted = state.get("extracted_entities", {})
    
    if extracted.get("is_skip"):
        # Just pass it through to validation
        extracted["extracted_values"] = {}
        return {"extracted_entities": extracted}
        
    entities = extracted.get("entities", [])
    
    for entity in entities:
        if entity["confidence"] < 0.8:
            logger.info(f"Low confidence ({entity['confidence']}) for {entity['field']}. Creating verification question.")
            # Create verification question
            q_text = f"I extracted '{entity['value']}' for {entity['field']}. Is this correct? (Reply Yes, or provide the correct value)"
            return {
                "current_question": {
                    "field": state["current_question"]["field"],
                    "section": state["current_question"]["section"],
                    "question_text": q_text,
                    "ui": "text",
                    "options": [],
                    "is_gate": state["current_question"].get("is_gate", False),
                    "missing_fields": state["current_question"].get("missing_fields", []),
                    "is_verification": True,
                    "verifying_field": entity["field"]
                }
            }
            
    # All entities verified or skipped
    logger.info("All extracted entities met confidence threshold.")
    extracted_values = {e["field"]: e["value"] for e in entities}
    
    extracted["extracted_values"] = extracted_values
    return {"extracted_entities": extracted}
