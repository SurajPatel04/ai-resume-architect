import logging
from langgraph.graph import StateGraph, END, START
from typing import Any, Dict

from app.graphs.state import ResumeState
from app.graphs.node.planner import planner
from app.graphs.node.tailor_resume import tailor_resume
from app.graphs.node.parse_document import parse_document
from app.graphs.node.analyze_gaps import analyze_gaps
from app.graphs.node.prioritize_queue import prioritize_queue
from app.graphs.node.generate_question import generate_question
from app.graphs.node.extract_entities import extract_entities
from app.graphs.node.verify_entities import verify_entities
from app.graphs.node.process_verification import process_verification
from app.graphs.node.validate_entities import validate_entities
from app.graphs.node.merge_profile import merge_profile
from app.graphs.node.enhance_resume import enhance_resume
from app.graphs.node.render_resume import render_resume

logger = logging.getLogger(__name__)

def route_start(state: ResumeState) -> str:
    """
    Router to determine if we need planning or if we are in the middle of a collection turn.
    """
    # For Phase 1, we always route user text inputs through the planner to determine intent
    if state.get("uploaded_text") or state.get("uploaded_file"):
        return "parse_document"
        
    if state.get("latest_answer"):
        return "planner"
        
    return "analyze_gaps"

def route_planner(state: ResumeState) -> str:
    """
    Router after planner node decides the workflow_type.
    """
    workflow_type = state.get("workflow_type")
    
    if workflow_type == "TAILOR_RESUME":
        return "tailor_resume"
        
    # Default to BUILD_PROFILE flow
    # If there is an active question they were answering, extract it
    if state.get("current_question") and state.get("latest_answer"):
        if state.get("current_question").get("is_verification"):
            return "process_verification"
        return "extract_entities"
        
    return "analyze_gaps"

def route_verification(state: ResumeState) -> str:
    extracted = state.get("extracted_entities", {})
    if "extracted_values" in extracted:
        return "validate_entities"
    return END

def route_after_validation(state: ResumeState) -> str:
    """
    If validation fails or user skips, skip merging and go to analyze_gaps.
    Otherwise, merge.
    """
    if state.get("validation_errors") or state.get("extracted_entities", {}).get("is_skip"):
        return "analyze_gaps"
    return "merge_profile"

def route_after_gaps(state: ResumeState) -> str:
    """
    Router that decides where to go after analyze_gaps.
    If there are items in the question_queue, prioritize them. Otherwise, we are done collecting.
    """
    queue = state.get("question_queue", [])
    if queue:
        return "prioritize_queue"
    
    return "enhance_resume"

# Initialize Graph
workflow = StateGraph(ResumeState)

# Add Nodes
workflow.add_node("planner", planner)
workflow.add_node("tailor_resume", tailor_resume)
workflow.add_node("parse_document", parse_document)
workflow.add_node("analyze_gaps", analyze_gaps)
workflow.add_node("prioritize_queue", prioritize_queue)
workflow.add_node("generate_question", generate_question)
workflow.add_node("extract_entities", extract_entities)
workflow.add_node("verify_entities", verify_entities)
workflow.add_node("process_verification", process_verification)
workflow.add_node("validate_entities", validate_entities)
workflow.add_node("merge_profile", merge_profile)
workflow.add_node("enhance_resume", enhance_resume)
workflow.add_node("render_resume", render_resume)

# Add Edges
workflow.add_conditional_edges(START, route_start, {
    "planner": "planner",
    "parse_document": "parse_document",
    "analyze_gaps": "analyze_gaps"
})

workflow.add_conditional_edges("planner", route_planner, {
    "tailor_resume": "tailor_resume",
    "extract_entities": "extract_entities",
    "process_verification": "process_verification",
    "analyze_gaps": "analyze_gaps"
})

workflow.add_edge("tailor_resume", "render_resume")
workflow.add_edge("parse_document", "analyze_gaps")

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
    "prioritize_queue": "prioritize_queue",
    "enhance_resume": "enhance_resume"
})

workflow.add_edge("prioritize_queue", "generate_question")

# After selecting a question, we end the graph execution to wait for user input
workflow.add_edge("generate_question", END)

workflow.add_edge("enhance_resume", "render_resume")
workflow.add_edge("render_resume", END)

# Export the uncompiled workflow
# We will compile it dynamically in main.py with the checkpointer
