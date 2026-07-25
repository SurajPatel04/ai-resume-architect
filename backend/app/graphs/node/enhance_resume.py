import logging
from typing import Any, Dict
from app.graphs.state import ResumeState, Resume
from app.utils.llm import get_openai_llm
from pydantic import BaseModel, Field
from typing import List

logger = logging.getLogger(__name__)

class EnhancedExperience(BaseModel):
    highlights: List[str] = Field(description="Polished highlights for this experience")

class EnhancedProject(BaseModel):
    highlights: List[str] = Field(description="Polished highlights for this project")

class EnhancedResume(BaseModel):
    summary_content: str = Field(description="Polished professional summary")
    experience: List[EnhancedExperience] = Field(description="List of enhanced experiences, in the same order as provided")
    projects: List[EnhancedProject] = Field(description="List of enhanced projects, in the same order as provided")

def enhance_resume(state: ResumeState) -> Dict[str, Any]:
    """
    Polishes the resume's bullets and summary for maximum impact using the LLM.
    Scoping the output to prevent hallucinated data loss of factual fields.
    """
    logger.info("Enhancing resume...")
    resume = state.get("master_profile", {})
    if hasattr(resume, "model_dump"):
        r = resume.model_dump()
    else:
        r = resume

    llm = get_openai_llm()
    structured_llm = llm.with_structured_output(EnhancedResume)

    prompt = f"""
    You are an expert resume writer. The user has provided their resume information.
    Your task is to heavily polish the professional summary, and the highlights/bullet points of their experience and projects.
    
    Guidelines:
    1. Rewrite highlights to use strong action verbs.
    2. Incorporate the STAR method (Situation, Task, Action, Result) where possible, highlighting metrics.
    3. Make the summary highly impactful and concise (3-4 sentences max).
    4. Fix any grammatical errors.
    5. Do NOT add fake metrics or experiences they didn't mention. If it's missing, just improve the phrasing.
    
    Here is the current raw resume data:
    {r}
    
    Output the enhanced fields in the exact same order as the raw data arrays.
    """

    try:
        enhanced: EnhancedResume = structured_llm.invoke(prompt)
        
        # Merge back safely
        if "summary" not in r:
            r["summary"] = {}
        r["summary"]["content"] = enhanced.summary_content
        
        for i, exp in enumerate(r.get("experience", [])):
            if i < len(enhanced.experience):
                exp["highlights"] = enhanced.experience[i].highlights
                
        for i, proj in enumerate(r.get("projects", [])):
            if i < len(enhanced.projects):
                proj["highlights"] = enhanced.projects[i].highlights
                
        # Re-validate the merged dict just to be safe
        validated_resume = Resume.model_validate(r)
        
        return {
            "master_profile": validated_resume.model_dump(),
            "phase": "enhancing"
        }
    except Exception as e:
        logger.error(f"Failed to enhance resume: {e}")
        return {"phase": "enhancing"} # fallback to original
