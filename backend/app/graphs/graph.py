import logging
from langgraph.graph import StateGraph, END, START

from app.graphs.state import ResumeState
from app.graphs.node.planner import planner
from app.graphs.node.apply_edit import apply_edit
from app.graphs.node.tailor_resume import tailor_resume
from app.graphs.node.parse_document import parse_document
from app.graphs.node.confirm_import import confirm_import
from app.graphs.node.add_content import ADD_SECTION, add_content
from app.graphs.node.analyze_gaps import analyze_gaps
from app.graphs.node.career_setup import CAREER_SECTION, ROLE_SECTION, career_setup
from app.graphs.node.conversation_planner import conversation_planner
from app.graphs.node.review_quality import review_quality
from app.graphs.node.generate_question import generate_question
from app.graphs.node.extract_entities import extract_entities
from app.graphs.node.verify_entities import verify_entities
from app.graphs.node.process_verification import process_verification
from app.graphs.node.validate_entities import validate_entities
from app.graphs.node.merge_profile import merge_profile
from app.graphs.node.enhance_resume import enhance_resume
from app.graphs.node.render_resume import FIT_SECTION, render_resume
from app.graphs.node.choose_style import STYLE_SECTION, choose_style
from app.graphs.node.score_ats import score_ats
from app.graphs.node.score_resume_quality import score_resume_quality
from app.graphs.node.skill_gap import skill_gap
from app.graphs.node.add_extras import add_extras

logger = logging.getLogger(__name__)

def route_start(state: ResumeState) -> str:
    """Router to determine if we need planning or if we are in the middle of a collection
    turn.
    """

    if state.get("uploaded_text") or state.get("uploaded_file"):
        return "parse_document"

    if state.get("latest_answer"):
        return "planner"

    return "analyze_gaps"

def route_planner(state: ResumeState) -> str:
    """Router after planner node decides the workflow_type."""
    workflow_type = state.get("workflow_type")
    current_question = state.get("current_question") or {}

    if current_question.get("section") == "import":
        return "confirm_import"

    # Checked ahead of workflow_type: the reply names a section, not an edit.
    if current_question.get("section") == FIT_SECTION:
        return "render_resume"

    # Likewise: a layout answer reads like a request to rewrite the resume.
    if current_question.get("section") == STYLE_SECTION:
        return "choose_style"

    if current_question.get("field") == "awaiting_jd":
        return "tailor_resume"

    # Ahead of the gate sections below: a message carrying a whole new entry is not an
    # answer to whatever happened to be on screen, and the gate that owns the question
    # has nowhere to put it.
    if workflow_type == "ADD_CONTENT":
        return "add_content"

    # Changing their mind about the layout, at any point after they first chose.
    if workflow_type == "RESTYLE":
        return "choose_style"

    # Answering "you already have this — add it anyway?" goes back to the node holding
    # the paste, whatever the classifier made of a chip about a duplicate.
    if current_question.get("section") == ADD_SECTION:
        return "add_content"

    if workflow_type == "TAILOR_RESUME":
        return "tailor_resume"

    if workflow_type == "EDIT_PROFILE":
        return "apply_edit"

    if workflow_type == "POLISH_RESUME":
        return "enhance_resume"

    if current_question.get("section") == "impact_gate":
        return "review_quality"

    if current_question.get("section") == "skill_gap":
        return "skill_gap"

    if current_question.get("section") in (CAREER_SECTION, ROLE_SECTION):
        return "career_setup"

    if current_question.get("section") == "add_extras":
        return "add_extras"

    if current_question and state.get("latest_answer"):
        if current_question.get("is_verification"):
            return "process_verification"
        return "extract_entities"

    return "analyze_gaps"

def route_verification(state: ResumeState) -> str:
    extracted = state.get("extracted_entities", {})

    if extracted.get("is_skip") or "items" in extracted or "extracted_values" in extracted:
        return "validate_entities"
    return END

def route_after_validation(state: ResumeState) -> str:
    """If validation fails or user skips, skip merging and go to analyze_gaps. Otherwise,
    merge.
    """
    if state.get("validation_errors") or state.get("extracted_entities", {}).get("is_skip"):
        return "analyze_gaps"
    return "merge_profile"

def nothing_left_to_ask(state: ResumeState) -> str:
    """Where to go once the question queue is empty."""
    if not state.get("quality_reviewed"):
        return "review_quality"

    if not state.get("extras_offered"):
        return "add_extras"

    return "enhance_resume"

def route_after_gaps(state: ResumeState) -> str:
    """Router that decides where to go after analyze_gaps. If there are items in the
    question_queue, let the planner choose between them. Otherwise the factual gaps are
    filled, and the two closing gates get their turn.
    """
    if state.get("question_queue"):
        return "conversation_planner"

    return nothing_left_to_ask(state)

def route_after_review(state: ResumeState) -> str:
    """review_quality asked the gate, queued what the user accepted, or found nothing."""
    if state.get("current_question"):
        return END

    if state.get("question_queue"):
        return "conversation_planner"

    return nothing_left_to_ask(state)

def route_after_planning(state: ResumeState) -> str:
    """The planner can drop the last section left to ask about, which ends the interview."""
    if state.get("active_target"):
        return "generate_question"

    return nothing_left_to_ask(state)

def route_after_extras(state: ResumeState) -> str:
    """Still adding things, or finished."""
    if state.get("current_question"):
        return END

    return "enhance_resume"

workflow = StateGraph(ResumeState)

workflow.add_node("planner", planner)
workflow.add_node("apply_edit", apply_edit)
workflow.add_node("tailor_resume", tailor_resume)
workflow.add_node("score_ats", score_ats)
workflow.add_node("score_resume_quality", score_resume_quality)
workflow.add_node("skill_gap", skill_gap)
workflow.add_node("career_setup", career_setup)
workflow.add_node("add_extras", add_extras)
workflow.add_node("parse_document", parse_document)
workflow.add_node("confirm_import", confirm_import)
workflow.add_node("add_content", add_content)
workflow.add_node("analyze_gaps", analyze_gaps)
workflow.add_node("conversation_planner", conversation_planner)
workflow.add_node("review_quality", review_quality)
workflow.add_node("generate_question", generate_question)
workflow.add_node("extract_entities", extract_entities)
workflow.add_node("verify_entities", verify_entities)
workflow.add_node("process_verification", process_verification)
workflow.add_node("validate_entities", validate_entities)
workflow.add_node("merge_profile", merge_profile)
workflow.add_node("enhance_resume", enhance_resume)
workflow.add_node("choose_style", choose_style)
workflow.add_node("render_resume", render_resume)

workflow.add_conditional_edges(START, route_start, {
    "planner": "planner",
    "parse_document": "parse_document",
    "analyze_gaps": "analyze_gaps"
})

workflow.add_conditional_edges("planner", route_planner, {
    "tailor_resume": "tailor_resume",
    "render_resume": "render_resume",
    "choose_style": "choose_style",
    "add_content": "add_content",
    "apply_edit": "apply_edit",
    "confirm_import": "confirm_import",
    "review_quality": "review_quality",
    "skill_gap": "skill_gap",
    "career_setup": "career_setup",
    "add_extras": "add_extras",
    "enhance_resume": "enhance_resume",
    "extract_entities": "extract_entities",
    "process_verification": "process_verification",
    "analyze_gaps": "analyze_gaps"
})

def route_after_edit(state: ResumeState) -> str:
    """Re-render only when something actually changed; a clarification just replies."""
    if state.get("edit_applied"):
        return "score_resume_quality"
    return END

workflow.add_conditional_edges("apply_edit", route_after_edit, {
    "score_resume_quality": "score_resume_quality",
    END: END,
})

def route_tailor_resume(state: ResumeState) -> str:
    if not state.get("job_description"):
        return END
    return "score_ats"

workflow.add_conditional_edges("tailor_resume", route_tailor_resume, {
    "score_ats": "score_ats",
    END: END
})
def route_after_scoring(state: ResumeState) -> str:
    """One shot at the keywords the job wants and the resume doesn't have."""
    if state.get("skill_gap_asked"):
        return "score_resume_quality"

    if (state.get("ats_feedback") or {}).get("missing_keywords"):
        return "skill_gap"

    return "score_resume_quality"

workflow.add_conditional_edges("score_ats", route_after_scoring, {
    "skill_gap": "skill_gap",
    "score_resume_quality": "score_resume_quality",
})

def route_after_skill_gap(state: ResumeState) -> str:
    """Re-score after an answer, so the number on screen reflects what they just added."""
    if state.get("current_question"):
        return END

    return "score_ats"

workflow.add_conditional_edges("skill_gap", route_after_skill_gap, {
    "score_ats": "score_ats",
    END: END,
})

workflow.add_edge("career_setup", "analyze_gaps")

workflow.add_edge("parse_document", "confirm_import")

def route_confirm_import(state: ResumeState) -> str:
    if state.get("import_confirmed"):
        return "analyze_gaps"
    return END

workflow.add_conditional_edges("confirm_import", route_confirm_import, {
    "analyze_gaps": "analyze_gaps",
    END: END,
})

def route_after_add_content(state: ResumeState) -> str:
    """Extract from what they pasted, wait on a question, or drop through.

    Two very different things arrive here as `current_question`. The standalone one is
    synthetic — nobody sees it, it exists to tell extract_entities which schema to parse
    the paste into. The duplicate question is a real one with chips on it, and running
    on past that both spends an extraction on a question about a button and puts a
    second question on screen underneath the first.
    """
    question = state.get("current_question") or {}

    if question.get("standalone"):
        return "extract_entities"

    if question:
        return END

    return "analyze_gaps"

workflow.add_conditional_edges("add_content", route_after_add_content, {
    "extract_entities": "extract_entities",
    "analyze_gaps": "analyze_gaps",
    END: END,
})

workflow.add_edge("extract_entities", "verify_entities")
workflow.add_edge("process_verification", "verify_entities")

workflow.add_conditional_edges("verify_entities", route_verification, {
    "validate_entities": "validate_entities",
    END: END
})

workflow.add_conditional_edges("validate_entities", route_after_validation, {
    "analyze_gaps": "analyze_gaps",
    "merge_profile": "merge_profile"
})
workflow.add_edge("merge_profile", "analyze_gaps")

workflow.add_conditional_edges("analyze_gaps", route_after_gaps, {
    "conversation_planner": "conversation_planner",
    "review_quality": "review_quality",
    "add_extras": "add_extras",
    "enhance_resume": "enhance_resume"
})

workflow.add_conditional_edges("review_quality", route_after_review, {
    "conversation_planner": "conversation_planner",
    "review_quality": "review_quality",
    "add_extras": "add_extras",
    "enhance_resume": "enhance_resume",
    END: END,
})

workflow.add_conditional_edges("add_extras", route_after_extras, {
    "enhance_resume": "enhance_resume",
    END: END,
})

workflow.add_conditional_edges("conversation_planner", route_after_planning, {
    "generate_question": "generate_question",
    "review_quality": "review_quality",
    "add_extras": "add_extras",
    "enhance_resume": "enhance_resume",
})

workflow.add_edge("generate_question", END)

workflow.add_edge("enhance_resume", "score_resume_quality")
workflow.add_edge("score_resume_quality", "choose_style")

def route_after_style(state: ResumeState) -> str:
    """Waiting on an answer about the layout, or ready to build the PDF."""
    if (state.get("current_question") or {}).get("section") == STYLE_SECTION:
        return END

    return "render_resume"

workflow.add_conditional_edges("choose_style", route_after_style, {
    "render_resume": "render_resume",
    END: END,
})
workflow.add_edge("render_resume", END)
