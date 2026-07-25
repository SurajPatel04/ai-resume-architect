import logging
import copy
from typing import Any, Dict
from app.graphs.state import ResumeState, Resume
from pydantic import ValidationError

logger = logging.getLogger(__name__)

def validate_entities(state: ResumeState) -> Dict[str, Any]:
    """
    Validates extracted entities deterministically using the Pydantic schema.
    Does NOT mutate the master_profile.
    Produces validation_errors if the dry-run merge fails schema checks.
    """
    logger.info("Validating extracted entities...")
    
    extracted_data = state.get("extracted_entities", {})
    is_skip = extracted_data.get("is_skip", False)
    extracted_values = extracted_data.get("extracted_values", {})
    
    current_question = state.get("current_question")
    if not current_question:
        return {}

    target_field = current_question.get("field")
    section_name = current_question.get("section")
    is_gate = current_question.get("is_gate", False)
    missing_fields = current_question.get("missing_fields", [])
    
    skipped = state.get("skipped", [])
    if skipped is None:
        skipped = []
        
    queue = state.get("question_queue", [])

    if is_skip:
        if is_gate and section_name:
            logger.info(f"User refused gate for section: {section_name}")
            skipped.append(section_name)
        else:
            logger.info(f"User skipped fields in {target_field}")
            for f in missing_fields:
                if target_field == "basics" or target_field == "skills":
                    skipped.append(f"{target_field}.{f}") if target_field == "basics" else skipped.append("skills")
                else:
                    skipped.append(f"{target_field}.{f}")
                    
        return {
            "skipped": skipped,
            "question_queue": queue[1:] if queue else [],
            "latest_answer": None,
            "current_question": None
        }

    if not extracted_values:
        # User didn't skip but no valid values were extracted
        return {
            "latest_answer": None,
            "current_question": None
        }

    # Dry-run merge to validate schema
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
    
    try:
        # Validate the mock updated resume
        Resume.model_validate(r)
        logger.info(f"Validation successful for {target_field}")
        return {
            "validation_errors": []
        }
    except ValidationError as ve:
        logger.warning(f"Validation failed after extraction for {target_field}: {ve}")
        errors = state.get("validation_errors", [])
        errors.append(f"Invalid extraction for {target_field}")
        return {
            "validation_errors": errors,
            "latest_answer": None,
            "current_question": None
        }
