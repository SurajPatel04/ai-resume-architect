import logging
from typing import Any, Dict, List
from app.graphs.state import ResumeState, Resume
from app.utils.llm import get_openai_llm
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TailoredExperience(BaseModel):
    highlights: List[str] = Field(
        description="Reworded highlights for this experience, reordered and rephrased to emphasize relevance to the target job. Same facts, no invented experience."
    )


class TailoredProject(BaseModel):
    highlights: List[str] = Field(
        description="Reworded highlights for this project, emphasizing relevance to the target job. Same facts, no invented experience."
    )


class TailoredResult(BaseModel):
    summary_content: str = Field(
        description="A professional summary rewritten to target the specific job. 3-4 sentences max."
    )
    experience: List[TailoredExperience] = Field(
        description="Tailored experiences, in the SAME order as provided."
    )
    projects: List[TailoredProject] = Field(
        description="Tailored projects, in the SAME order as provided."
    )
    skills_order: List[str] = Field(
        default_factory=list,
        description="The candidate's EXISTING skill keywords, reordered so the ones most relevant to the job come first. Do not add skills the candidate doesn't have."
    )


def tailor_resume(state: ResumeState) -> Dict[str, Any]:
    """
    Tailors the master_profile against a job description.
    Rewrites summary + highlights and reorders skills to emphasize JD-relevant content,
    WITHOUT inventing experience. Writes the result to generated_resumes["tailored"].
    Never mutates master_profile.
    """
    logger.info("Tailoring resume against job description...")

    job_description = state.get("job_description")

    if not job_description or not job_description.strip():
        logger.info("No job_description present. Asking user to provide one.")
        return {
            "current_question": {
                "field": "system",
                "question_text": "Sure — paste the job description you'd like me to tailor your resume for.",
                "ui": "text",
                "options": []
            }
        }

    master_profile = state.get("master_profile", {})
    if hasattr(master_profile, "model_dump"):
        r = master_profile.model_dump()
    else:
        r = master_profile

    llm = get_openai_llm()
    structured_llm = llm.with_structured_output(TailoredResult)

    prompt = f"""
    You are an expert resume writer tailoring a candidate's resume to a specific job.

    TARGET JOB DESCRIPTION:
    ---
    {job_description}
    ---

    CANDIDATE'S CURRENT RESUME DATA:
    ---
    {r}
    ---

    Your task:
    1. Rewrite the professional summary to position the candidate for THIS job (3-4 sentences max).
    2. Rewrite and reorder the highlights of each experience and project to emphasize what matters most for this job. Lead with the most relevant, impactful bullets.
    3. Reorder the candidate's EXISTING skills so the most job-relevant ones come first.

    STRICT RULES:
    - Do NOT invent experience, metrics, skills, or achievements the candidate did not mention.
    - Only rephrase, reorder, and re-emphasize what is already there.
    - Keep experience and project arrays in the EXACT same order as provided (only the highlights inside them change).
    - Mirror the job description's terminology where it truthfully matches the candidate's real experience.
    """

    try:
        tailored: TailoredResult = structured_llm.invoke(prompt)

        if "summary" not in r or r["summary"] is None:
            r["summary"] = {}
        r["summary"]["content"] = tailored.summary_content

        for i, exp in enumerate(r.get("experience", [])):
            if i < len(tailored.experience):
                exp["highlights"] = tailored.experience[i].highlights

        for i, proj in enumerate(r.get("projects", [])):
            if i < len(tailored.projects):
                proj["highlights"] = tailored.projects[i].highlights

        if tailored.skills_order and r.get("skills"):
            existing = set()
            for cat in r["skills"]:
                existing.update(cat.get("keywords", []))
            
            ordered = [s for s in tailored.skills_order if s in existing]
            leftovers = [s for s in existing if s not in ordered]
            final_keywords = ordered + leftovers
            
            if r["skills"]:
                r["skills"][0]["keywords"] = final_keywords
                for cat in r["skills"][1:]:
                    cat["keywords"] = [k for k in cat.get("keywords", []) if k not in final_keywords]

        tailored_resume = Resume.model_validate(r)

        generated = state.get("generated_resumes", {})
        generated["tailored"] = tailored_resume

        return {
            "generated_resumes": generated,
        }

    except Exception as e:
        logger.error(f"Failed to tailor resume: {e}")
        generated = state.get("generated_resumes", {})
        if hasattr(master_profile, "model_dump"):
            generated["tailored"] = master_profile.__class__.model_validate(master_profile.model_dump())
        else:
            generated["tailored"] = master_profile
        return {"generated_resumes": generated}
