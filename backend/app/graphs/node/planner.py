import logging
from typing import Any, Dict, Literal, Optional
from app.graphs.state import ResumeState
from pydantic import BaseModel, Field
from app.utils.llm import get_openai_llm

logger = logging.getLogger(__name__)

class PlannerResult(BaseModel):
    workflow_type: Literal["BUILD_PROFILE", "TAILOR_RESUME", "EDIT_PROFILE", "POLISH_RESUME"] = Field(
        description=(
            "The workflow to execute. BUILD_PROFILE if the user is answering questions, providing resume details, or starting fresh. "
            "TAILOR_RESUME if they explicitly ask to tailor, optimize, or format their resume for a specific job or role. "
            "EDIT_PROFILE if they ask to change a SPECIFIC value to another SPECIFIC value "
            "(e.g. 'change my location to Noida', 'that company name is wrong', 'drop the second project'). "
            "POLISH_RESUME if they ask for better WRITING rather than different FACTS — 'make the project "
            "points more professional', 'reword my bullets', 'this sounds weak'. The distinction is whether "
            "they named a new value: if they did it is EDIT_PROFILE, if they only named a quality it is POLISH_RESUME."
        )
    )
    has_jd: bool = Field(
        default=False,
        description="True if the user's message contained a job description or text to tailor the resume against."
    )

TAILOR_HINTS = (
    "tailor", "job description", "job posting", "optimi", "this role",
    "this job", "apply for", "job desc", "jd for", "customize",
)

EDIT_HINTS = (
    "change", "update", "correct", "wrong", "replace", "instead of", "rename",
    "remove", "delete", "edit", "fix ", "should be", "mistake", "typo",
)

POLISH_HINTS = (
    "professional", "polish", "rewrite", "reword", "improve", "better", "stronger",
    "sounds weak", "impressive",
)

def wants_tailoring(answer: str) -> bool:
    return any(hint in (answer or "").lower() for hint in TAILOR_HINTS)

def wants_interrupt(answer: str) -> bool:
    """Does this reply look like something other than an answer to the open question?

    Deliberately generous. A false positive costs one intent call and still lands on
    BUILD_PROFILE; a false negative silently swallows what the user asked for.
    """
    lowered = (answer or "").lower()
    return wants_tailoring(answer) or any(
        hint in lowered for hint in EDIT_HINTS + POLISH_HINTS
    )

def skips_intent_call(state: ResumeState, latest_answer: str) -> bool:
    """True when the reply can only be an answer to the question we just asked.

    The interview asks a question and the user answers it — classifying that is a
    whole LLM call to rediscover what the state already says. `system` is excluded
    because a system message must never capture the next turn, and any request that
    looks like tailoring or an edit has to be able to interrupt.
    """
    pending = state.get("current_question") or {}
    field = pending.get("field")
    if not field or field == "system":
        return False

    answer = (latest_answer or "").strip().casefold()
    options = {(str(option).strip().casefold()) for option in (pending.get("options") or [])}
    if answer and answer in options:
        return True

    return not wants_interrupt(latest_answer)

def planner(state: ResumeState) -> Dict[str, Any]:
    """
    Analyzes the user's latest input to determine the overall intent and workflow.
    """
    logger.info("Planner analyzing intent...")
    latest_answer = state.get("latest_answer")
    current_workflow = state.get("workflow_type")

    if not latest_answer:
        return {"workflow_type": current_workflow or "BUILD_PROFILE"}

    if skips_intent_call(state, latest_answer):
        logger.info("Answering a pending question — skipping the intent call.")
        return {"workflow_type": "BUILD_PROFILE"}

    llm = get_openai_llm()
    structured_llm = llm.with_structured_output(PlannerResult, method="function_calling")
    
    prompt = f"""
    The user is interacting with an AI Resume Architect.
    Current Workflow: {current_workflow or 'None'}
    User's latest message: "{latest_answer}"
    
    Determine whether the user wants to build their master profile (providing personal
    details, answering questions about experience), tailor their existing resume for a
    specific job/role, or edit something already in their resume.
    If they are answering a question previously asked by the AI, it is BUILD_PROFILE.
    If they are asking to change or correct a detail that is already recorded, it is EDIT_PROFILE.
    
    If their intent is to tailor the resume (TAILOR_RESUME) and their message contains the job description text, set `has_jd` to true.
    If they want to tailor it but did not provide the job description, set `has_jd` to false.
    """

    try:
        result: PlannerResult = structured_llm.invoke(prompt)
        logger.info(f"Planner decided workflow: {result.workflow_type}, has_jd: {result.has_jd}")

        updates: Dict[str, Any] = {"workflow_type": result.workflow_type}

        if result.workflow_type == "TAILOR_RESUME":
            if result.has_jd:
                                                                                    
                updates["job_description"] = latest_answer
            else:

                updates["job_description"] = None

        return updates
    except Exception as e:
        logger.error(f"Planner failed: {e}")
        return {"workflow_type": current_workflow or "BUILD_PROFILE"}

if __name__ == "__main__":
    def state(field=None, section="", answer="Acme Corp"):
        q = {"field": field, "section": section} if field else None
        return {"current_question": q, "latest_answer": answer}

    assert skips_intent_call(state("experience[0]"), "Acme Corp")
    assert skips_intent_call(state("basics"), "surajpatel9390@gmail.com")
    assert skips_intent_call(state("experience[0]", section="impact"), "21-30%")
    assert skips_intent_call(state("skills"), "Not sure")
                                                                                      
    assert skips_intent_call(state("career_level"), "Working full-time")
    assert skips_intent_call(state("target_role"), "Backend Engineer")
    assert skips_intent_call(
        {"current_question": {"field": "skills", "options": ["Yes, update my resume"]}},
        "Yes, update my resume",
    )

    assert not skips_intent_call(state("system"), "here is the job description")
    assert not skips_intent_call(state("system"), "can you change the location to Noida")

    assert not skips_intent_call(state(None), "hello")

    for interrupt in (
        "actually, tailor this for a job",
        "Can you optimize my resume for this role?",
        "here's the job description",
        "I want to apply for this instead",
        "customize it please",
        "can you change the location lucknow to Noida",
        "that company name is wrong",
        "remove the second project",
        "update my email",
        "it should be Noida",
    ):
        assert not skips_intent_call(state("experience[0]"), interrupt), interrupt

    for ordinary in ("I led a team of four", "Careerboat", "Python, FastAPI, Redis"):
        assert skips_intent_call(state("experience[0]"), ordinary), ordinary

    for chip in (
        "Not sure", "Yes, that's right", "10-20%", "21-30%", "31-50%",
        "50%", "75%", "90%", "20-30%", "10-15%", "50% or more",
        "30% faster processing", "50% reduction in errors", "Saved $10,000 annually",
    ):
        assert skips_intent_call(state("experience[0]"), chip), f"chip billed a call: {chip}"

    from app.graphs.node.add_extras import CERT_CHIP, DONE_CHIP, SKILLS_CHIP
    from app.graphs.node.career_setup import CAREER_CHIPS, ROLE_CHIPS
    from app.graphs.node.confirm_import import CONFIRM_CHIP
    from app.graphs.node.generate_question import IMPACT_OPTIONS, SKIP_CHIP
    from app.graphs.node.review_quality import DECLINE_CHIP, IMPROVE_CHIP
    from app.graphs.node.skill_gap import NONE_CHIP

    for chip in (*IMPACT_OPTIONS, *CAREER_CHIPS, *ROLE_CHIPS,
                 CONFIRM_CHIP, IMPROVE_CHIP, DECLINE_CHIP, NONE_CHIP, SKIP_CHIP,
                 CERT_CHIP, SKILLS_CHIP, DONE_CHIP, "Tailor for another job"):
        if chip == "Tailor for another job":
            continue                                           
        assert not wants_interrupt(chip), f"chip trips the interrupt detector: {chip!r}"

    for polish in (
        "update the all the points of the project make it professional way",
        "rewrite my bullets",
        "can you make this sound better",
        "improve the wording",
    ):
        assert wants_interrupt(polish), polish

    assert wants_tailoring("TAILOR this") and not wants_tailoring("")
    assert wants_interrupt("please update my phone") and not wants_interrupt("")

    routes = PlannerResult.model_fields["workflow_type"].annotation.__args__
    assert "EDIT_PROFILE" in routes and "POLISH_RESUME" in routes

    assert "job_description" not in PlannerResult.model_fields

    print("planner ok")
