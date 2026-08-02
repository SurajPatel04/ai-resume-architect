import logging
from typing import Any, Dict, Literal
from app.graphs.apply import read_slot
from app.graphs.node.choose_style import wants_own_style, wants_site_style
from app.graphs.prompts import INTENT
from app.graphs.state import ResumeState
from pydantic import BaseModel, Field
from app.utils.llm import get_openai_llm

logger = logging.getLogger(__name__)

class PlannerResult(BaseModel):
    workflow_type: Literal[
        "BUILD_PROFILE", "TAILOR_RESUME", "EDIT_PROFILE", "POLISH_RESUME", "ADD_CONTENT",
        "RESTYLE",
    ] = Field(
        description=(
            "The workflow to execute. BUILD_PROFILE if the user is answering questions, providing resume details, or starting fresh. "
            "TAILOR_RESUME if they explicitly ask to tailor, optimize, or format their resume for a specific job or role. "
            "EDIT_PROFILE if they ask to change a SPECIFIC value to another SPECIFIC value "
            "(e.g. 'change my location to Noida', 'that company name is wrong', 'drop the second project'). "
            "POLISH_RESUME if they ask for better WRITING rather than different FACTS — 'make the project "
            "points more professional', 'reword my bullets', 'this sounds weak'. The distinction is whether "
            "they named a new value: if they did it is EDIT_PROFILE, if they only named a quality it is POLISH_RESUME. "
            "ADD_CONTENT if the message CARRIES a whole new entry to put on the resume — a project with its "
            "bullets, a job, a degree, certifications — rather than answering the question that was asked. "
            "'add this project' followed by the project itself is ADD_CONTENT, not EDIT_PROFILE. "
            "RESTYLE if they are talking about how the PDF LOOKS rather than what it says — the "
            "layout, the template, the design, wanting their own original formatting back."
        )
    )
    add_section: str = Field(
        default="",
        description="For ADD_CONTENT only: which section the entry belongs in. One of "
        "experience, education, projects, skills, certifications. Empty otherwise.",
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

# Phrases, not the bare word "add": someone answering a question about a job writes
# "added a caching layer" and means it as the answer. A false positive here costs one
# intent call and still lands on BUILD_PROFILE; a false negative files a pasted project
# under whatever section happened to be open.
# How the page looks, as opposed to what it says. Kept apart from POLISH_HINTS, which is
# about the writing: "make this look like my original" is a layout request and has
# nothing to do with rewording anything.
LAYOUT_HINTS = (
    "layout", "template", "design", "formatting", "original format", "my format",
    "looks like", "look like my", "same style as",
)

ADD_HINTS = (
    "add this", "add these", "add it to", "add my", "add another", "add the following",
    "also add", "put this in", "include this", "here is another", "here's another",
)

POLISH_HINTS = (
    "professional", "polish", "rewrite", "reword", "improve", "better", "stronger",
    "sounds weak", "impressive",
)

def wants_tailoring(answer: str) -> bool:
    return any(hint in (answer or "").lower() for hint in TAILOR_HINTS)

def mentions_layout(answer: str) -> bool:
    """Does the message say anything at all about how the page looks?"""
    return any(hint in (answer or "").lower() for hint in LAYOUT_HINTS)

# Enough to tell "add the skill in the Java" from a request about the design, for the
# one job of deciding what a wrongly-classified RESTYLE should have been.
CONTENT_HINTS = EDIT_HINTS + ADD_HINTS + ("add ", "skill", "include ", "put ")

def wants_content_change(answer: str) -> bool:
    return any(hint in (answer or "").lower() for hint in CONTENT_HINTS)

def wants_interrupt(answer: str) -> bool:
    """Does this reply look like something other than an answer to the open question?"""
    lowered = (answer or "").lower()
    return wants_tailoring(answer) or any(
        hint in lowered for hint in EDIT_HINTS + POLISH_HINTS + ADD_HINTS + LAYOUT_HINTS
    )

def fills_a_blank(pending: Dict[str, Any], answer: str) -> bool:
    """Is this reply one of our own sentences with the blank filled in?"""
    meta = pending.get("meta") or {}
    templates = [meta.get("template") or ""]
    templates += [gap.get("template") or "" for gap in (meta.get("gaps") or [])]

    lines = [line.strip() for line in (answer or "").splitlines() if line.strip()]
    return any(read_slot(t, line) for t in templates if t for line in lines)

# Questions whose reply route_planner picks by section rather than by intent. A chip tap
# there is unambiguous, but typed prose is often something else entirely, and the node
# that owns the gate has no way to hand it back — so it has to be classified first.
FLOW_GATES = {"impact_gate", "import", "add_extras", "skill_gap", "fit_page",
              "choose_style", "add_content"}

def skips_intent_call(state: ResumeState, latest_answer: str) -> bool:
    """True when the reply can only be an answer to the question we just asked."""
    pending = state.get("current_question") or {}
    field = pending.get("field")
    if not field or field == "system":
        return False

    answer = (latest_answer or "").strip().casefold()
    options = {(str(option).strip().casefold()) for option in (pending.get("options") or [])}
    if answer and answer in options:
        return True

    # A filled-in metric template is our own wording coming back; never an interrupt.
    if fills_a_blank(pending, latest_answer):
        return True

    # A gate that has moved past its opening question is collecting a specific thing —
    # an issuer, a credential link — and the reply is the answer to that, however much
    # it reads like new content on its own.
    if pending.get("section") in FLOW_GATES and (pending.get("step") or "gate") == "gate":
        return False

    return not wants_interrupt(latest_answer)

def planner(state: ResumeState) -> Dict[str, Any]:
    """Analyzes the user's latest input to determine the overall intent and workflow."""
    logger.info("Planner analyzing intent...")
    latest_answer = state.get("latest_answer")
    current_workflow = state.get("workflow_type")

    if not latest_answer:
        return {"workflow_type": current_workflow or "BUILD_PROFILE"}

    if skips_intent_call(state, latest_answer):
        logger.info("Answering a pending question — skipping the intent call.")
        return {"workflow_type": "BUILD_PROFILE"}

    # "give me site layout" says which layout it wants. Asking a classifier to work that
    # out is a round trip that can come back wrong, and when it does the person is shown
    # the two chips again and has to answer the question they just answered. Both
    # directions, because both are things people type.
    if wants_own_style(latest_answer) or wants_site_style(latest_answer):
        logger.info("A layout choice, read straight off the message.")
        return {"workflow_type": "RESTYLE"}

    llm = get_openai_llm()
    structured_llm = llm.with_structured_output(PlannerResult, method="function_calling")

    try:
        result: PlannerResult = structured_llm.invoke(
            INTENT.format(workflow=current_workflow or "None", answer=latest_answer)
        )
        logger.info(f"Planner decided workflow: {result.workflow_type}, has_jd: {result.has_jd}")

        kind = result.workflow_type

        # A restyle names a layout. The classifier reaches for it on messages that say
        # nothing about how the page looks — "add the skill in the Java" came back as
        # one — and the layout question then goes to someone who asked for a skill and
        # never got it.
        if kind == "RESTYLE" and not mentions_layout(latest_answer):
            kind = "EDIT_PROFILE" if wants_content_change(latest_answer) else "BUILD_PROFILE"
            logger.info("RESTYLE on a message with no layout in it; %s instead.", kind)

        updates: Dict[str, Any] = {"workflow_type": kind}

        if kind == "ADD_CONTENT":
            updates["add_section"] = result.add_section

        if kind == "TAILOR_RESUME":
            if result.has_jd:

                updates["job_description"] = latest_answer
            else:

                updates["job_description"] = None

        return updates
    except Exception as e:
        logger.error(f"Planner failed: {e}")
        return {"workflow_type": current_workflow or "BUILD_PROFILE"}
