import logging
from typing import Any, Dict, Literal
from app.graphs.state import ResumeState
from pydantic import BaseModel, Field
from app.utils.llm import get_openai_llm

logger = logging.getLogger(__name__)

class PlannerResult(BaseModel):
    workflow_type: Literal["BUILD_PROFILE", "TAILOR_RESUME"] = Field(
        description="The workflow to execute. Use BUILD_PROFILE if the user is answering questions, providing resume details, or starting fresh. Use TAILOR_RESUME if the user explicitly asks to tailor, optimize, or format their resume for a specific job or role."
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
    """
    
    try:
        result: PlannerResult = structured_llm.invoke(prompt)
        logger.info(f"Planner decided workflow: {result.workflow_type}")
        return {"workflow_type": result.workflow_type}
    except Exception as e:
        logger.error(f"Planner failed: {e}")
        return {"workflow_type": current_workflow or "BUILD_PROFILE"}
