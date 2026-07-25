import logging
from typing import Any, Dict, Literal, Optional
from app.graphs.state import ResumeState
from pydantic import BaseModel, Field
from app.utils.llm import get_openai_llm

logger = logging.getLogger(__name__)

class PlannerResult(BaseModel):
    workflow_type: Literal["BUILD_PROFILE", "TAILOR_RESUME"] = Field(
        description="The workflow to execute. Use BUILD_PROFILE if the user is answering questions, providing resume details, or starting fresh. Use TAILOR_RESUME if the user explicitly asks to tailor, optimize, or format their resume for a specific job or role."
    )
    job_description: Optional[str] = Field(
        default=None,
        description="The extracted job description text if the user provided one in their message. Do not make this up."
    )
    has_jd: bool = Field(
        default=False,
        description="True if the user's message contained a job description or text to tailor the resume against."
    )

def planner(state: ResumeState) -> Dict[str, Any]:
    """
    Analyzes the user's latest input to determine the overall intent and workflow.
    """
    logger.info("Planner analyzing intent...")
    latest_answer = state.get("latest_answer")
    current_workflow = state.get("workflow_type")
    
    # If there's no latest answer, default to BUILD_PROFILE
    if not latest_answer:
        return {"workflow_type": current_workflow or "BUILD_PROFILE"}

    llm = get_openai_llm()
    structured_llm = llm.with_structured_output(PlannerResult, method="function_calling")
    
    prompt = f"""
    The user is interacting with an AI Resume Architect.
    Current Workflow: {current_workflow or 'None'}
    User's latest message: "{latest_answer}"
    
    Determine if the user's intent is to build their master profile (providing personal details, answering questions about experience) or to tailor their existing resume for a specific job/role.
    If they are answering a question previously asked by the AI, it is BUILD_PROFILE.
    
    If their intent is to tailor the resume (TAILOR_RESUME) and they provided the job description text, extract it into `job_description` and set `has_jd` to true.
    If they want to tailor it but did not provide the job description, set `has_jd` to false.
    """
    
    try:
        result: PlannerResult = structured_llm.invoke(prompt)
        logger.info(f"Planner decided workflow: {result.workflow_type}, has_jd: {result.has_jd}")
        
        updates: Dict[str, Any] = {"workflow_type": result.workflow_type}
        
        if result.workflow_type == "TAILOR_RESUME":
            if result.has_jd and result.job_description:
                updates["job_description"] = result.job_description
            else:
                # We flag that JD is missing so the graph can route to asking for it
                updates["job_description"] = None
                
        return updates
    except Exception as e:
        logger.error(f"Planner failed: {e}")
        return {"workflow_type": current_workflow or "BUILD_PROFILE"}
