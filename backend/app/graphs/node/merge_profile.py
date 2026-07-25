import logging
import copy
from typing import Any, Dict
from app.graphs.state import ResumeState, Resume

logger = logging.getLogger(__name__)

def merge_profile(state: ResumeState) -> Dict[str, Any]:
    """
    Deterministically merges the extracted_entities into master_profile.
    Only runs if validation succeeds.
    """
    logger.info("Merging extracted entities into master profile...")
    
    extracted_data = state.get("extracted_entities", {})
    extracted_values = extracted_data.get("extracted_values", {})
    
    current_question = state.get("current_question")
    if not current_question or not extracted_values:
        return {
            "latest_answer": None,
            "current_question": None
        }

    target_field = current_question.get("field")
    if not target_field:
        return {
            "latest_answer": None,
            "current_question": None
        }

    resume = state.get("master_profile", {})
    if hasattr(resume, "model_dump"):
        r = resume.model_dump()
    else:
        r = copy.deepcopy(resume)
        
    parts = target_field.split('.')
    current = r
    
    for i, part in enumerate(parts):
        if '[' in part and ']' in part:
            list_name, index_str = part.replace(']', '').split('[')
            index = int(index_str)
            if list_name not in current:
                current[list_name] = []
            while len(current[list_name]) <= index:
                current[list_name].append({})
            
            if i == len(parts) - 1:
                current = current[list_name][index]
            else:
                current = current[list_name][index]
        elif i == len(parts) - 1:
            if part not in current:
                current[part] = {}
            current = current[part]
        else:
            if part not in current:
                current[part] = {}
            current = current[part]
            
    if target_field == "skills":
        if "skills" in extracted_values:
            val = extracted_values["skills"]
            if isinstance(val, list):
                if not current:
                    current.append({"name": "Core Skills", "keywords": val})
                else:
                    current[0]["keywords"].extend(val)
    else:
        for key, val in extracted_values.items():
            if isinstance(current.get(key), list) and not isinstance(val, list):
                if isinstance(val, str):
                    vals = [v.strip() for v in val.replace('\\n', ',').split(',')]
                    vals = [v for v in vals if v]
                    current[key].extend(vals)
                else:
                    current[key].append(val)
            else:
                current[key] = val
                
    # At this point, r has been validated by validate_entities, so we just convert it to Resume
    validated_resume = Resume.model_validate(r)
    
    queue = state.get("question_queue", [])
    is_gate = current_question.get("is_gate", False)
    
    if is_gate:
        logger.info("Gate question successfully answered. Clearing queue to force rebuild for new fields.")
        new_queue = []
    else:
        new_queue = queue[1:] if queue else []
    
    return {
        "master_profile": validated_resume.model_dump(),
        "question_queue": new_queue,
        "latest_answer": None,
        "current_question": None
    }
