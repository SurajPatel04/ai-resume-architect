import logging
from typing import Any, Dict, List
from app.graphs.state import Education, Experience, Project, Resume, ResumeState
from app.graphs.apply import apply_extraction, impact_key
from app.graphs.node.conversation_planner import MAX_EXCHANGES
from app.graphs.node.generate_question import current_item
from app.schemas.schema import merge_typed_items

logger = logging.getLogger(__name__)

ITEM_MODELS = {"experience": Experience, "education": Education, "projects": Project}

MAX_EXTRA_ITEMS = 5

def append_items(merged: Dict[str, Any], section: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Add entries the same answer described beyond the one that was asked about."""
    model = ITEM_MODELS.get(section)
    if not model or not items:
        return merged

    entries = list(merged.get(section) or [])
    for raw in items[:MAX_EXTRA_ITEMS]:
        if not isinstance(raw, dict) or not any(raw.values()):
            continue
        try:

            built = apply_extraction({}, f"{section}[0]", raw)[section][0]
            entries.append(model.model_validate(built).model_dump())
        except Exception as e:
            logger.warning("Discarding an unusable extra %s entry %r: %r", section, raw, e)

    if len(entries) == len(merged.get(section) or []):
        return merged

    logger.info("The answer described %d further %s entr(y/ies).",
                len(entries) - len(merged.get(section) or []), section)
    return {**merged, section: entries}

def advance(
    queue: List[Dict[str, Any]],
    question: Dict[str, Any],
    merged: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """The question queue after an answer has landed."""
    if question.get("is_gate"):
        return []

    # Volunteered content answered no queued question, so it must not retire one.
    if question.get("standalone"):
        return queue

    if not queue:
        return []

    item = current_item(merged, question.get("field") or "")

    asked = [f for f in (question.get("missing_fields") or []) if f in item]
    unanswered = [f for f in asked if not item[f]]

    if not unanswered or len(unanswered) == len(asked):
        return queue[1:]

    logger.info("%s still missing %s — staying on it.", question.get("field"), unanswered)
    return [{
        **queue[0],
        "missing_fields": unanswered,
        "reason": f"Still missing: {', '.join(unanswered)}.",
    }] + queue[1:]

def merge_profile(state: ResumeState) -> Dict[str, Any]:
    """Deterministically merges the extracted_entities into master_profile. Only runs if
    validation succeeds.
    """
    logger.info("Merging extracted entities into master profile...")

    extracted = state.get("extracted_entities", {})
    extracted_values = extracted.get("extracted_values", {})
    typed_items = extracted.get("items")
    current_question = state.get("current_question")

    done = {"latest_answer": None, "current_question": None}
    if not current_question or not current_question.get("field"):
        return done

    done["exchanges"] = (state.get("exchanges") or [])[-(MAX_EXCHANGES - 1):] + [{
        "question": current_question.get("question_text"),
        "answer": state.get("latest_answer"),
        "field": current_question["field"],
        "values": typed_items if typed_items is not None else extracted_values,
        "confidence": (
            {f"{c.get('item', 0)}.{c['field']}": c.get("confidence", 1.0)
             for c in extracted.get("confidence") or []}
            if typed_items is not None else
            {e["field"]: e.get("confidence", 1.0) for e in extracted.get("entities") or []}
        ),

        "sufficiency": extracted.get("sufficiency", "sufficient"),
        "gap": extracted.get("gap", ""),
        "follow_up": bool(current_question.get("is_follow_up")),
        "judged": False,
    }]

    target_field = current_question["field"]
    bullet_index = current_question.get("bullet_index")

    skipped = list(state.get("skipped") or [])
    if current_question.get("section") == "impact":

        skipped.append(impact_key(target_field, bullet_index))

    queue = state.get("question_queue", [])

    if not (typed_items or extracted_values):

        return {**done, "skipped": skipped,
                "question_queue": [] if current_question.get("is_gate") else queue[1:]}

    resume = state.get("master_profile", {})
    if hasattr(resume, "model_dump"):
        resume = resume.model_dump()

    if typed_items is not None:

        before = len(resume.get(current_question.get("section") or "") or [])
        merged = Resume.model_validate(merge_typed_items(
            resume, current_question.get("section") or "", target_field, typed_items
        )).model_dump()
        grew = len(merged.get(current_question.get("section") or "") or []) > before
    else:

        merged = Resume.model_validate(
            apply_extraction(
                resume, target_field, extracted_values, bullet_index,
                # Same template validate_entities dry-ran, or the two disagree.
                template=(current_question.get("meta") or {}).get("template"),
            )
        ).model_dump()
        with_extras = append_items(merged, current_question.get("section") or "",
                                   extracted.get("extra_items") or [])
        grew = with_extras is not merged
        merged = with_extras

    if current_question.get("is_gate"):
        logger.info("Gate question answered. Clearing queue to force rebuild for the new fields.")

    return {
        **done,
        "master_profile": merged,

        "question_queue": [] if grew else advance(queue, current_question, merged),
        "skipped": skipped,
    }
