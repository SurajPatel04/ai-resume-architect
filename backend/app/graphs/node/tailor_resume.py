import logging
from typing import Any, Dict, List
from app.graphs.state import ResumeState, Resume
from app.utils.llm import get_openai_llm
from app.graphs.node.enhance_resume import aligned
from app.graphs.prompts import TAILOR
from app.utils.prompt import compact
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class TailoredExperience(BaseModel):
    company: str = Field(
        default="",
        description="The employer this entry is about, copied exactly from the input, so its "
        "highlights can be matched back to the right job.",
    )
    highlights: List[str] = Field(
        description="Reworded highlights for this experience, reordered and rephrased to emphasize relevance to the target job. Same facts, no invented experience."
    )

class TailoredProject(BaseModel):
    name: str = Field(
        default="",
        description="The project's name, copied exactly from the input, so its highlights can be "
        "matched back to the right project.",
    )
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
    """Tailors the master_profile against a job description. Rewrites summary + highlights and
    reorders skills to emphasize JD-relevant content, WITHOUT inventing experience. Writes
    the result to generated_resumes["tailored"]. Never mutates master_profile.
    """
    logger.info("Tailoring resume against job description...")

    job_description = state.get("job_description")
    pending = state.get("current_question") or {}
    latest_answer = state.get("latest_answer")

    if not job_description and latest_answer and pending.get("field") == "awaiting_jd":
        job_description = latest_answer

    if not job_description or not job_description.strip():
        logger.info("No job_description present. Asking user to provide one.")
        ask = "Sure — paste the job description you'd like me to tailor your resume for."
        return {

            "current_question": {
                "field": "awaiting_jd",
                "question_text": ask,
                "ui": "text",
                "options": []
            },
        }

    master_profile = state.get("master_profile", {})
    if hasattr(master_profile, "model_dump"):
        r = master_profile.model_dump()
    else:
        r = master_profile

    llm = get_openai_llm()
    structured_llm = llm.with_structured_output(TailoredResult)

    try:
        tailored: TailoredResult = structured_llm.invoke(
            TAILOR.format(job_description=job_description, resume=compact(r))
        )

        if "summary" not in r or r["summary"] is None:
            r["summary"] = {}
        r["summary"]["content"] = tailored.summary_content

        # Matched by name, not by slot — same reason as enhance_resume: a reordered
        # response otherwise writes one entry's bullets onto another.
        jobs = r.get("experience", [])
        for exp, match in zip(jobs, aligned(jobs, tailored.experience, "company")):
            if match is not None:
                exp["highlights"] = match.highlights

        works = r.get("projects", [])
        for proj, match in zip(works, aligned(works, tailored.projects, "name")):
            if match is not None:
                proj["highlights"] = match.highlights

        if tailored.skills_order and r.get("skills"):

            rank = {s: i for i, s in enumerate(tailored.skills_order)}
            for cat in r["skills"]:
                cat["keywords"] = sorted(
                    cat.get("keywords", []),
                    key=lambda k: rank.get(k, len(rank)),
                )

        # Dumped, not a model: generated_resumes is checkpointed.
        tailored_resume = Resume.model_validate(r).model_dump()

        generated = state.get("generated_resumes", {})
        generated["tailored"] = tailored_resume

        return {
            "generated_resumes": generated,
            "job_description": job_description,
            "latest_answer": None,
            "current_question": None,
        }

    except Exception as e:
        logger.error(f"Failed to tailor resume: {e}")
        generated = state.get("generated_resumes", {})
        generated["tailored"] = (
            master_profile.model_dump() if hasattr(master_profile, "model_dump") else master_profile
        )
        return {
            "generated_resumes": generated,
            "job_description": job_description,
            "latest_answer": None,
            "current_question": None,
        }