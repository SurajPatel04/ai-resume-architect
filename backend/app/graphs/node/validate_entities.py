import logging
from typing import Any, Dict
from app.graphs.state import ResumeState, Resume
from app.graphs.apply import apply_extraction, impact_key
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
    bullet_index = current_question.get("bullet_index")

    skipped = list(state.get("skipped") or [])
    queue = state.get("question_queue", [])

    if is_skip:
        if section_name == "impact":
                                                                         
            logger.info(f"User skipped the metric for {target_field}[{bullet_index}]")
            skipped.append(impact_key(target_field, bullet_index))
        elif is_gate and section_name:
            logger.info(f"User refused gate for section: {section_name}")
            skipped.append(section_name)
        elif target_field == "skills":
            skipped.append("skills")
        else:
            logger.info(f"User skipped fields in {target_field}")
            skipped.extend(f"{target_field}.{f}" for f in missing_fields)

        return {
            "skipped": skipped,
            "question_queue": queue[1:] if queue else [],
            "latest_answer": None,
            "current_question": None
        }

    if not extracted_values:
                                                             
        return {
            "latest_answer": None,
            "current_question": None
        }

    resume = state.get("master_profile", {})
    if hasattr(resume, "model_dump"):
        resume = resume.model_dump()

                                                                               
    candidate = apply_extraction(resume, target_field, extracted_values, bullet_index)

    try:
        Resume.model_validate(candidate)
        logger.info(f"Validation successful for {target_field}")
        return {
            "validation_errors": []
        }
    except ValidationError as ve:
        logger.warning(f"Validation failed after extraction for {target_field}: {ve}")
        errors = list(state.get("validation_errors") or [])
        errors.append(f"Invalid extraction for {target_field}")
        return {
            "validation_errors": errors,
            "latest_answer": None,
            "current_question": None
        }