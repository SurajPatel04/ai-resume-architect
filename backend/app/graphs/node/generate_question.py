import logging
from typing import Any, Dict
from app.graphs.state import ResumeState
from app.utils.llm import get_openai_llm
from pydantic import BaseModel, Field
from typing import List, Literal

logger = logging.getLogger(__name__)

class GeneratedQuestion(BaseModel):
    question_text: str = Field(description="The short, polite question to ask the user.")
    ui: Literal["text", "chips"] = Field(description="Use 'chips' if there are 2-5 distinct short options (e.g. Yes/No, or specific skills), otherwise use 'text'.")
    options: List[str] = Field(default_factory=list, description="A list of 2-5 short options if ui is 'chips'.")

def generate_question(state: ResumeState) -> Dict[str, Any]:
    """
    Uses the LLM to generate the natural language question based on active_target.
    Returns the result in state.current_question.
    """
    target_gap = state.get("active_target")
    if not target_gap:
        return {"current_question": None}

    llm = get_openai_llm()

    errors = state.get("validation_errors", [])
    error_context = ""
    if errors:
        error_context = f"\n\nCRITICAL: The user's previous answer for this field failed validation! Error: {errors[-1]}\nYou MUST apologize and politely re-ask the user to provide the information in the correct format."

    missing_fields = target_gap.get("missing_fields", [])
    is_gate = target_gap.get("is_gate", False)
    
    missing_str = ", ".join(missing_fields) if missing_fields else "the information"

    if target_gap.get("section") == "impact":
        instructions = f"""
    The user's resume contains this bullet point, but it states no measurable result:
    "{target_gap.get('weak_bullet', '')}"

    Ask ONE short question that gets them to quantify the outcome — a percentage, a
    count, an amount of money, time saved, team size, whatever actually fits this bullet.
    Set ui to 'chips' and offer 3-4 plausible magnitudes plus "Not sure", so they can
    answer with a single tap instead of typing.
        """
    elif is_gate:
        instructions = f"""
    The user's resume is entirely missing the '{target_gap['section']}' section.
    You must ask a SINGLE question that achieves TWO things:
    1. Asks if they have any {target_gap['section']} to add (the gate).
    2. If they do, asks them to provide all of these specific details about their first entry: {missing_str}.
    
    Example: "Do you have any work experience? If so, tell me about your most recent role — what was the company, your title, and what did you achieve?"
    
    Set ui to 'text' because this requires a detailed response if they say yes.
        """
    else:
        instructions = f"""
    The user's resume is missing specific fields for the item {target_gap['field']}.
    Specifically, these fields are missing and need to be filled: {missing_str}.
    Reason: {target_gap['reason']}
    
    Ask a short, conversational question to gather ONLY these missing fields: {missing_str}.
    Do NOT ask for fields that are already filled. Combine the request for these missing fields into one smooth question.
    
    If the requested fields have clear, common answers (like 3-5 common skills for their role), set ui to 'chips' and provide those as options.
    Otherwise, if it requires a free-text response, set ui to 'text' and leave options empty.
        """

    prompt = f"""
    You are an expert resume assistant.
    {error_context}

    {instructions}
    
    Keep the question polite and under 2 sentences.
    """

    try:
        structured_llm = llm.with_structured_output(GeneratedQuestion)
        response: GeneratedQuestion = structured_llm.invoke(prompt)
        question_text = response.question_text
        ui = response.ui
        options = response.options
    except Exception as e:
        logger.error(f"Failed to generate question: {e}")
        question_text = f"Could you please provide information for {target_gap['field']}? ({target_gap['reason']})"
        ui = "text"
        options = []

    return {
        "current_question": {
            "field": target_gap["field"],
            "question_text": question_text,
            "section": target_gap.get("section", ""),
            "ui": ui,
            "options": options,
            "is_gate": is_gate,
            "missing_fields": missing_fields,
                                                                                 
                                                
            "bullet_index": target_gap.get("bullet_index"),
        },
        "validation_errors": []
    }