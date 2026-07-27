import logging
import re
from typing import Any, Dict
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

FLAT_SCHEMAS = {
    "impact": ("metric", MetricExtraction,
               "Pull out the figure or outcome they gave for that bullet. Take the number "
               "as they said it — never round it, scale it, or supply one they did not give."),
}

def _typed(section: str, question: Dict[str, Any], answer: str,
           recent_exchanges: list[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract directly into the section's typed Resume model."""
    schema = SECTION_EXTRACTION_SCHEMAS[section]

    prompt = f"""
    The user is filling in the {section} section of their resume.

    Question asked: {question.get('question_text')}
    What it was about: {question.get('missing_fields') or 'this entry'}
    Their answer: {answer}

    Most recent interview turns (use only to avoid repeating an already answered or
    skipped field): {recent_exchanges[-2:]}

    Fill in `items` with the actual {section} models. One item per {section} entry
    described, in the order the user gave them.

    For skills, each item is a named category. Preserve explicit headings exactly, such
    as `Languages: JavaScript, TypeScript` or `Tools & DevOps: Docker, Git`; put the
    heading in `name` and every listed skill in `keywords`. Do not collapse categories.

    - The question is about ONE entry, but people answer with two jobs or two degrees in
      a single message. Anything you leave out is lost — nothing later asks for it again.
    - Take everything they gave, not only what was asked for. Dates, a location, a link
      mentioned in passing all have a field here and all belong in it.
    - Leave a field at its default when they did not give it. Never guess it, never carry a value
      from one entry to another, and never fill one from what you happen to know about
      the company or university they named.
    - Bullet points belong to the entry they were written under, one per line. Never
      create generic responsibilities from only a company name or job title: `highlights`
      must contain only work details the user actually wrote or spoke.

    Set is_skip if they declined or said they have none, and put nothing in `items`.

    Then rate `sufficiency`. Ask yourself whether a hiring manager reading this on a
    finished resume would see something real. "abc" or "asdf" as an institution is not a
    university, it is a placeholder — that is 'unusable', however cleanly it parsed.
    Being brief is not the same as being empty: "Acme" is a complete company name.
    """

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
    """
    Extracts data from the user's latest answer using an LLM.
    Returns typed Resume-model items (or a flat fallback) for validation and merge.
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

    prompt = f"""
    The user was asked a question while filling in their resume.

    Question asked: {question.get('question_text')}
    Their answer: {answer}

    {instruction}

    Set is_skip if they declined or said they have none, and leave the value empty.

    Then rate `sufficiency`. Ask yourself whether a hiring manager reading this on a
    finished resume would see something real. "abc" or "asdf" is not an answer, it is a
    placeholder — that is 'unusable', however cleanly it parsed. Being brief is not the
    same as being empty: "Python, Go" is a complete skills answer.
    """

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
    """A question about nothing in the Resume model — a planner follow-up that named a
    section with no schema. The only path left that describes its fields in prose.
    """
    missing_fields = question.get("missing_fields", [])

    prompt = f"""
    The user was asked to provide information for their resume.
    Section: {question.get('section')}
    Target Item: {question.get('field')}
    Requested Fields: {missing_fields}
    Question Asked: {question.get('question_text')}
    User's Answer: {answer}

    Determine if the user provided the information or if they explicitly skipped/declined.
    If they provided information, extract each provided field into the `entities` list with a confidence score.
    CRITICAL INSTRUCTION: Only include entities that the user ACTUALLY answered. If the user provided 2 out of 3 requested fields, the 3rd field MUST be omitted entirely.
    Use only the field names listed above: a name that is not one of them is dropped
    silently and the user's answer is lost.

    Then rate `sufficiency`. Ask yourself whether a hiring manager reading this value on a
    finished resume would see something real. "abc" or "asdf" as an institution is not a
    university, it is a placeholder — that is 'unusable', however cleanly it parsed.
    Being brief is not the same as being empty: "Acme" is a complete company name.
    """

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

if __name__ == "__main__":
    from app.schemas.schema import EducationExtraction

    parsed = EducationExtraction.model_validate({
        "is_skip": False,
        "items": [{"institution": "Amity", "area": "MCA"}],
        "confidence": [{"item": 0, "field": "institution", "confidence": 0.9}],
    })
    assert parsed.items[0].institution == "Amity"
    assert parsed.confidence[0].item == 0
    assert is_explicit_skip("Skip this") and is_explicit_skip("No, skip this")
    assert is_gate_affirmation("Yes") and not is_gate_affirmation("Careerboat")
    assert supplied_work_dates("Dec 2025, currently working") == {
        "start_date": "Dec 2025", "end_date": "Present"
    }
    print("extract_entities typed schemas ok")
