import logging
import re
from typing import Any, Dict
from app.graphs.apply import read_slot
from app.graphs.prompts import (
    EXTRACT_FLAT, EXTRACT_FREEFORM, EXTRACT_TYPED, METRIC_INSTRUCTION,
)
from app.graphs.state import ResumeState
from app.schemas.schema import (
    FreeformExtraction,
    MetricExtraction,
    SECTION_EXTRACTION_SCHEMAS,
)
from app.utils.llm import get_openai_llm

logger = logging.getLogger(__name__)

EXPLICIT_SKIP_ANSWERS = {
    "skip this",
    "skip this one",
    "no, skip this",
    "i don't have a number",
}

_MONTH_YEAR = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{4}\b",
    re.I,
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_PRESENT = re.compile(r"\b(?:present|current(?:ly)?|ongoing|still\s+working)\b", re.I)
_YES = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "yes please", "correct"}

def is_explicit_skip(answer: str) -> bool:
    """Chip taps must never depend on an LLM correctly recognizing a skip."""
    return (answer or "").strip().casefold() in EXPLICIT_SKIP_ANSWERS

def is_gate_affirmation(answer: str) -> bool:
    """A Yes tap opens the next blank entry; it is never resume data to extract."""
    return (answer or "").strip().strip(".,!").casefold() in _YES

def supplied_work_dates(answer: str) -> Dict[str, str]:
    """Reliable fallback for short date replies such as "Dec 2025, currently working"."""
    dates = _MONTH_YEAR.findall(answer or "") or _YEAR.findall(answer or "")
    values: Dict[str, str] = {}
    if dates:
        values["start_date"] = dates[0]
    if len(dates) > 1:
        values["end_date"] = dates[1]
    elif _PRESENT.search(answer or ""):
        values["end_date"] = "Present"
    return values

def recent_turns(exchanges: list[Dict[str, Any]], keep: int = 2) -> str:
    """The last couple of question/answer pairs, and nothing else off the exchange."""
    return "\n".join(
        f"Q: {e.get('question')}\nA: {e.get('answer')}"
        for e in (exchanges or [])[-keep:]
    ) or "Nothing yet."

FLAT_SCHEMAS = {
    "impact": ("metric", MetricExtraction, METRIC_INSTRUCTION),
}

def _typed(section: str, question: Dict[str, Any], answer: str,
           recent_exchanges: list[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract directly into the section's typed Resume model."""
    schema = SECTION_EXTRACTION_SCHEMAS[section]

    prompt = EXTRACT_TYPED.format(
        section=section,
        question=question.get("question_text"),
        about=question.get("missing_fields") or "this entry",
        answer=answer,
        recent=recent_turns(recent_exchanges),
    )

    result = get_openai_llm().with_structured_output(schema, method="function_calling").invoke(prompt)

    payload = result.model_dump(exclude_defaults=True)
    payload.setdefault("items", [])

    if section == "experience":
        dates = supplied_work_dates(answer)
        if dates:
            if payload["items"]:
                payload["items"][0] = {**payload["items"][0], **dates}
            else:
                payload["items"] = [dates]

    logger.info("Extraction (%s) - is_skip: %s, sufficiency: %s, entries: %d",
                section, result.is_skip, result.sufficiency, len(payload.get("items", [])))

    return payload

def extract_entities(state: ResumeState) -> Dict[str, Any]:
    """Extracts data from the user's latest answer using an LLM. Returns typed Resume-model
    items (or a flat fallback) for validation and merge.
    """
    logger.info("Extracting entities from user input...")
    latest_answer = state.get("latest_answer")
    current_question = state.get("current_question")

    if not latest_answer or not current_question:
        return {"extracted_entities": {"is_skip": False, "entities": []}}

    target_field = current_question.get("field")
    section_name = current_question.get("section")
    missing_fields = current_question.get("missing_fields", [])

    if not target_field:
        return {"extracted_entities": {"is_skip": False, "entities": []}}

    if is_explicit_skip(latest_answer):
        logger.info("User explicitly skipped %s.", target_field)
        return {"extracted_entities": {"is_skip": True, "items": [], "entities": []}}

    if current_question.get("is_gate") and is_gate_affirmation(latest_answer):
        logger.info("User accepted gate %s; opening a blank entry without extraction.", target_field)
        return {"extracted_entities": {"is_skip": False, "items": [], "entities": []}}

    figure = read_slot((current_question.get("meta") or {}).get("template") or "", latest_answer)
    if figure:
        # The filled-in line is already the sentence going on the resume.
        logger.info("Read %r out of the filled-in bullet for %s; no extraction needed.",
                    figure, target_field)
        return {"extracted_entities": {
            "is_skip": False,
            "entities": [{"field": "metric", "value": figure, "confidence": 1.0, "item": 0}],
            "sufficiency": "sufficient",
            "gap": "",
        }}

    try:

        if section_name in SECTION_EXTRACTION_SCHEMAS:
            return {"extracted_entities": _typed(
                section_name, current_question, latest_answer, state.get("exchanges") or []
            )}

        if section_name in FLAT_SCHEMAS:
            return {"extracted_entities": _flat(section_name, current_question, latest_answer)}

        return {"extracted_entities": _freeform(current_question, latest_answer)}
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        return {"extracted_entities": {"is_skip": False, "entities": []}}

def _flat(section: str, question: Dict[str, Any], answer: str) -> Dict[str, Any]:
    """Extract a question that has no entry behind it into the one field it asks for."""
    field, schema, instruction = FLAT_SCHEMAS[section]

    prompt = EXTRACT_FLAT.format(
        question=question.get("question_text"), answer=answer, instruction=instruction
    )

    result = get_openai_llm().with_structured_output(schema, method="function_calling").invoke(prompt)
    value = getattr(result, field)

    logger.info("Extraction (%s) - is_skip: %s, sufficiency: %s, value: %r",
                section, result.is_skip, result.sufficiency, value)

    return {
        "is_skip": result.is_skip,

        "entities": [{"field": field, "value": value, "confidence": 1.0, "item": 0}] if value else [],
        "sufficiency": result.sufficiency,
        "gap": result.gap,
    }

def _freeform(question: Dict[str, Any], answer: str) -> Dict[str, Any]:
    """A question about nothing in the Resume model — a planner follow-up that named a section
    with no schema. The only path left that describes its fields in prose.
    """
    missing_fields = question.get("missing_fields", [])

    prompt = EXTRACT_FREEFORM.format(
        section=question.get("section"),
        field=question.get("field"),
        missing=missing_fields,
        question=question.get("question_text"),
        answer=answer,
    )

    result: FreeformExtraction = get_openai_llm().with_structured_output(
        FreeformExtraction, method="function_calling"
    ).invoke(prompt)

    logger.info("Extraction (free-form) - is_skip: %s, sufficiency: %s, entities: %s",
                result.is_skip, result.sufficiency, [e.field for e in result.entities])

    return {
        "is_skip": result.is_skip,
        "entities": [e.model_dump() for e in result.entities],
        "sufficiency": result.sufficiency,
        "gap": result.gap,
    }
