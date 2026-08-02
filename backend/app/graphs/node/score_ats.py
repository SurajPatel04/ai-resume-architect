import logging
from typing import Any, Dict, List
from app.graphs.state import ResumeState
from app.utils.llm import get_openai_llm
from app.graphs.prompts import ATS_SCORE
from app.utils.prompt import compact
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class ATSResult(BaseModel):
    score: int = Field(description="ATS match score from 0 to 100 for how well the resume fits the job description.")
    matched_keywords: List[str] = Field(
        default_factory=list,
        description="Important keywords/skills from the job description that ARE present in the resume."
    )
    missing_keywords: List[str] = Field(
        default_factory=list,
        description="Important keywords/skills from the job description that are NOT present in the resume."
    )
    feedback: str = Field(
        description="2-3 sentences of concrete, actionable feedback on how to improve the match. No fabricated advice."
    )

def score_ats(state: ResumeState) -> Dict[str, Any]:
    """Scores the tailored resume against the job description (0-100) and produces a short
    keyword/gap breakdown. JD-only: if no JD, skip scoring.
    """
    logger.info("Scoring resume against job description (ATS)...")

    job_description = state.get("job_description")
    if not job_description or not job_description.strip():
        logger.info("No job_description; skipping ATS scoring.")
        return {}

    generated = state.get("generated_resumes", {})
    resume = generated.get("tailored") or state.get("master_profile", {})
    if hasattr(resume, "model_dump"):
        r = resume.model_dump()
    else:
        r = resume

    llm = get_openai_llm()
    structured_llm = llm.with_structured_output(ATSResult)

    try:
        result: ATSResult = structured_llm.invoke(
            ATS_SCORE.format(job_description=job_description, resume=compact(r))
        )
        logger.info(f"ATS score: {result.score}")
        return {
            "ats_score": result.score,
            "ats_feedback": {
                "matched_keywords": result.matched_keywords,
                "missing_keywords": result.missing_keywords,
                "feedback": result.feedback,
            },
        }
    except Exception as e:
        logger.error(f"ATS scoring failed: {e}")
        return {}
