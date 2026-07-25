import logging
from typing import Any, Dict
from app.graphs.state import ResumeState

logger = logging.getLogger(__name__)

def tailor_resume(state: ResumeState) -> Dict[str, Any]:
    """
    Stub node for tailoring the resume. 
    In Phase 1, it simply copies the master_profile to generated_resumes["tailored"].
    """
    logger.info("Tailoring resume based on user request...")
    
    master_profile = state.get("master_profile")
    generated = state.get("generated_resumes", {})
    
    # Deep copy using model_dump -> model_validate
    if hasattr(master_profile, "model_dump"):
        tailored_profile = master_profile.__class__.model_validate(master_profile.model_dump())
    else:
        tailored_profile = master_profile

    generated["tailored"] = tailored_profile
    
    return {
        "generated_resumes": generated,
        "current_question": {
            "field": "system",
            "question_text": "I've started a tailored version of your resume based on your master profile! (This is a placeholder for actual AI tailoring).",
            "ui": "text",
            "options": []
        }
    }
