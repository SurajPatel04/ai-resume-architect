import logging
from typing import Any, Dict
from app.graphs.state import ResumeState, Resume
from app.graphs.apply import apply_extraction, impact_key

logger = logging.getLogger(__name__)


def merge_profile(state: ResumeState) -> Dict[str, Any]:
    """
    Deterministically merges the extracted_entities into master_profile.
    Only runs if validation succeeds.
    """
    logger.info("Merging extracted entities into master profile...")

    extracted_values = state.get("extracted_entities", {}).get("extracted_values", {})
    current_question = state.get("current_question")

    done = {"latest_answer": None, "current_question": None}
    if not current_question or not current_question.get("field"):
        return done

    target_field = current_question["field"]
    bullet_index = current_question.get("bullet_index")

    skipped = list(state.get("skipped") or [])
    if current_question.get("section") == "impact":
                                                                                     
                                                                              
                                            
        skipped.append(impact_key(target_field, bullet_index))

    queue = state.get("question_queue", [])
    if current_question.get("is_gate"):
        logger.info("Gate question answered. Clearing queue to force rebuild for the new fields.")
        new_queue = []
    else:
        new_queue = queue[1:] if queue else []

    if not extracted_values:
        return {**done, "skipped": skipped, "question_queue": new_queue}

    resume = state.get("master_profile", {})
    if hasattr(resume, "model_dump"):
        resume = resume.model_dump()

                                                                                           
    merged = apply_extraction(resume, target_field, extracted_values, bullet_index)

    return {
        **done,
        "master_profile": Resume.model_validate(merged).model_dump(),
        "question_queue": new_queue,
        "skipped": skipped,
    }