import logging
from typing import Any, Dict
from app.graphs.state import ResumeState, Resume
from app.graphs.apply import apply_extraction, impact_key
from app.graphs.node.generate_question import says_yes
from app.schemas.schema import merge_typed_items
from pydantic import ValidationError

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2

def mark_skipped(skipped: list, question: Dict[str, Any]) -> list:
    """Record that `question` will not be answered, in the form analyze_gaps reads back.

    Every kind of gap is filtered by a different key — a gate drops its whole section, a
    metric drops one bullet, everything else drops named fields. Written once so the
    "user declined" and "we gave up asking" paths cannot mark it differently.
    """
    target_field = question.get("field")
    section_name = question.get("section")
    missing_fields = question.get("missing_fields", [])

    if section_name == "impact":
        skipped.append(impact_key(target_field, question.get("bullet_index")))
    elif question.get("skip_section_if_empty") and section_name:
                                                                                   
        skipped.append(section_name)
    elif question.get("is_gate") and section_name:
        skipped.append(section_name)
    elif target_field == "skills":
        skipped.append("skills")
    else:
        skipped.extend(f"{target_field}.{f}" for f in missing_fields)
    return skipped

def validate_entities(state: ResumeState) -> Dict[str, Any]:
    """
    Validates extracted entities deterministically using the Pydantic schema.
    Does NOT mutate the master_profile.
    Produces validation_errors if the dry-run merge fails schema checks.
    """
    logger.info("Validating extracted entities...")

    extracted_data = state.get("extracted_entities", {})
    is_skip = extracted_data.get("is_skip", False)
    extracted_values = extracted_data.get("extracted_values", {})
    typed_items = extracted_data.get("items")

    current_question = state.get("current_question")
    if not current_question:
        return {}

    target_field = current_question.get("field")
    section_name = current_question.get("section")
    missing_fields = current_question.get("missing_fields", [])
    bullet_index = current_question.get("bullet_index")
    is_gate = current_question.get("is_gate", False)

    resume = state.get("master_profile", {})
    if hasattr(resume, "model_dump"):
        resume = resume.model_dump()

    skipped = list(state.get("skipped") or [])
    queue = state.get("question_queue", [])

    def move_on() -> Dict[str, Any]:
        """Stop asking about this gap and let the queue advance."""
        history = (state.get("exchanges") or [])[-5:] + [{
            "question": current_question.get("question_text"),
            "answer": state.get("latest_answer"),
            "field": target_field,
            "values": {},
            "confidence": {},
            "sufficiency": "skipped",
            "gap": "user explicitly declined this question",
            "follow_up": bool(current_question.get("is_follow_up")),
            "judged": True,
        }]
        return {
            "validation_errors": [],
            "skipped": mark_skipped(skipped, current_question),
            "question_queue": queue[1:] if queue else [],
            "latest_answer": None,
            "current_question": None,
            "exchanges": history,
        }

    def retry(reason: str) -> Dict[str, Any]:
        """Re-ask with an apology — or give up once it is clear the answer won't land.

        Returning without an error used to drop straight through: merge_profile bails on a
        null current_question, so nothing popped the queue and generate_question re-emitted
        the byte-identical question at temperature 0. A gate question invites "yes", which
        extracts to nothing, so the commonest possible reply looped forever.
        """
        errors = list(state.get("validation_errors") or [])
        errors.append(reason)

        if len(errors) < MAX_ATTEMPTS:
            logger.info("Re-asking %s: %s", target_field, reason)
            return {"validation_errors": errors, "latest_answer": None, "current_question": None}

        logger.info("Moving on from %s after %d attempts", target_field, len(errors))
        return move_on()

    if is_skip:
        logger.info("User skipped %s (section %s)", target_field, section_name)
        return move_on()

    if is_gate and not (typed_items or extracted_values) and "[" in (target_field or "")\
            and says_yes(state.get("latest_answer")):
        opened = apply_extraction(resume, target_field, {})
        try:
            profile = Resume.model_validate(opened).model_dump()
        except ValidationError as ve:
            logger.warning("Could not open an entry at %s: %s", target_field, ve)
            return retry(f"Could not start a new {section_name} entry.")

        logger.info("Gate accepted; opened an empty %s entry.", target_field)
        return {
                                                                                         
            "question_queue": [],
            "master_profile": profile,
            "validation_errors": [],
            "latest_answer": None,
            "current_question": None,
        }

    if extracted_data.get("sufficiency") == "unusable":
        gap = extracted_data.get("gap") or "it doesn't read like a real answer"
        logger.info("Unusable answer for %s: %s", target_field, gap)
        return retry(f"What they gave for {target_field} isn't usable: {gap}.")

    if not (typed_items or extracted_values):
        wanted = ", ".join(missing_fields) or target_field
        return retry(f"Their reply held no answer for: {wanted}.")

    if typed_items is not None:
        candidate = merge_typed_items(resume, section_name, target_field, typed_items)
    else:
        candidate = apply_extraction(resume, target_field, extracted_values, bullet_index)

    try:
        Resume.model_validate(candidate)
        logger.info(f"Validation successful for {target_field}")
        return {
            "validation_errors": []
        }
    except ValidationError as ve:
        logger.warning(f"Validation failed after extraction for {target_field}: {ve}")
        return retry(f"What they gave for {target_field} isn't a valid value.")

if __name__ == "__main__":
    GATE = {"field": "experience[0]", "section": "experience", "is_gate": True,
            "missing_fields": ["company", "position", "highlights"]}
    QUEUE = [{"field": "experience[0]"}, {"field": "education[0]"}]

    def run(question=GATE, entities=None, is_skip=False, errors=None, profile=None,
            sufficiency="sufficient", gap=""):
        return validate_entities({
            "current_question": question,
            "question_queue": list(QUEUE),
            "extracted_entities": {"is_skip": is_skip, "extracted_values": entities or {},
                                   "sufficiency": sufficiency, "gap": gap},
            "validation_errors": list(errors or []),
            "skipped": [],
            "master_profile": profile or {},
        })

    first = run()
    assert first["validation_errors"], "a dead-end answer must record why"
    assert "question_queue" not in first, "the gap stays queued while we re-ask"
    assert first["current_question"] is None and first["latest_answer"] is None

    last = run(errors=first["validation_errors"])
    assert last["question_queue"] == QUEUE[1:], last["question_queue"]
    assert last["validation_errors"] == [], "the count resets for the next gap"
    assert last["skipped"] == ["experience"], "a gate gives up on its whole section"

    assert run(entities={"company": "Acme"}, errors=["stale"])["validation_errors"] == []

    EDU = {"field": "education[0]", "section": "education", "missing_fields": ["institution", "area"]}
    junk = run(EDU, entities={"institution": "abc"}, sufficiency="unusable",
               gap="gave a placeholder, not a real institution")
    assert junk["validation_errors"], "a placeholder must be re-asked, not merged"
    assert "placeholder" in junk["validation_errors"][-1], junk["validation_errors"]
    assert "question_queue" not in junk, "the gap stays queued while we re-ask"

    assert run(EDU, entities={"institution": "abc"}, sufficiency="unusable",
               errors=junk["validation_errors"])["question_queue"] == QUEUE[1:]

    assert run(EDU, entities={"institution": "IIT"}, sufficiency="thin",
               gap="no area of study")["validation_errors"] == []
                                                             
    assert run(entities={"company": "Acme"})["validation_errors"] == []

    skip = run(is_skip=True)
    assert skip["question_queue"] == QUEUE[1:] and skip["skipped"] == ["experience"]

    yes = validate_entities({
        "current_question": GATE, "question_queue": list(QUEUE), "latest_answer": "Yes",
        "extracted_entities": {"is_skip": False, "extracted_values": {}},
        "validation_errors": [], "skipped": [], "master_profile": {},
    })
    assert yes["master_profile"]["experience"] == [{
        "company": "", "position": "", "location": "", "start_date": "", "end_date": "", "highlights": [],
    }], yes["master_profile"]["experience"]
    assert yes["question_queue"] == [], "cleared so analyze_gaps rebuilds against the new entry"
    assert yes["validation_errors"] == [], "a tap is not a failed attempt"
    assert "skipped" not in yes, "saying yes must not mark the section skipped"

    skills_gate = {"field": "skills", "section": "skills", "is_gate": True, "missing_fields": []}
    assert validate_entities({
        "current_question": skills_gate, "question_queue": list(QUEUE), "latest_answer": "Yes",
        "extracted_entities": {"is_skip": False, "extracted_values": {}},
        "validation_errors": [], "skipped": [], "master_profile": {},
    })["validation_errors"], "no slot to open means this is still an unanswered question"

    assert mark_skipped([], {"field": "experience[0]", "section": "impact", "bullet_index": 2})\
        == ["impact.experience[0].2"]
    assert mark_skipped([], {"field": "skills", "section": "skills"}) == ["skills"]
    assert mark_skipped([], {"field": "projects[0]", "section": "projects",
                              "skip_section_if_empty": True}) == ["projects"]
    assert mark_skipped([], {"field": "basics", "section": "basics", "missing_fields": ["phone", "linkedin"]})\
        == ["basics.phone", "basics.linkedin"]

    assert validate_entities({"current_question": None}) == {}

    print("validate_entities ok")
