import logging
from typing import Any, Dict, List
from app.graphs.apply import LIST_FIELDS
from app.graphs.node.generate_question import is_affirmation
from app.graphs.state import ResumeState

logger = logging.getLogger(__name__)

MULTI_VALUE = LIST_FIELDS | {"skills"}

def collect_values(entities: List[Dict[str, Any]]) -> Dict[str, Any]:
    """entities -> {field: value}, keeping every answer when a field is named twice."""
    values: Dict[str, Any] = {}

    for entity in entities:
        field, value = entity.get("field"), entity.get("value")

        if field not in values:
            values[field] = value
            continue

        if field not in MULTI_VALUE:
            logger.warning("Two answers for %r; keeping the first (%r, not %r).",
                           field, values[field], value)
            continue

        head = values[field] if isinstance(values[field], list) else [values[field]]
        tail = value if isinstance(value, list) else [value]
        values[field] = head + tail

    return values

def group_items(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Entities split into the entries they describe, the one that was asked about first."""
    by_item: Dict[int, List[Dict[str, Any]]] = {}

    for entity in entities:
        try:
            index = max(0, int(entity.get("item") or 0))
        except (TypeError, ValueError):
            index = 0
        by_item.setdefault(index, []).append(entity)

    return [collect_values(by_item[key]) for key in sorted(by_item)]

CONFIRM_BELOW = 0.65

CONFIRM_CHIP = "Yes, that's right"

def verify_entities(state: ResumeState) -> Dict[str, Any]:
    """Checks the confidence of extracted entities. Anything below CONFIRM_BELOW is put
    straight back to the user; the rest is converted to extracted_values, carrying its
    confidence forward for the planner to weigh.
    """
    logger.info("Verifying extracted entities confidence...")
    extracted = state.get("extracted_entities", {})

    if extracted.get("is_skip"):
        return {"extracted_entities": extracted}

    if "items" in extracted:
        items = list(extracted.get("items") or [])
        asked = state.get("current_question") or {}

        if asked.get("is_gate"):
            items = [
                {key: value for key, value in item.items() if not is_affirmation(value)}
                for item in items
            ]
            items = [item for item in items if item]

        for confidence in extracted.get("confidence") or []:
            item_index = confidence.get("item", 0)
            field = confidence.get("field")
            score = confidence.get("confidence", 1.0)
            if score >= CONFIRM_BELOW or not isinstance(item_index, int)\
                    or item_index < 0 or item_index >= len(items) or field not in items[item_index]:
                continue

            value = items[item_index][field]
            return {
                "current_question": {
                    "field": asked.get("field"),
                    "section": asked.get("section", ""),
                    "question_text": f"I extracted '{value}' for {field}. Is this correct?",
                    "ui": "chips",
                    "options": [CONFIRM_CHIP],
                    "is_gate": asked.get("is_gate", False),
                    "missing_fields": asked.get("missing_fields", []),
                    "bullet_index": asked.get("bullet_index"),
                    "is_verification": True,
                    "verifying_item": item_index,
                    "verifying_field": field,
                },
            }

        extracted["items"] = items
        return {"extracted_entities": extracted}

    entities = extracted.get("entities", [])
    asked = state.get("current_question") or {}

    if asked.get("is_gate"):
        tapped = [e for e in entities if is_affirmation(e.get("value"))]
        if tapped:
            logger.info("Gate tap, not data — discarding %s.", [e["field"] for e in tapped])
            entities = [e for e in entities if e not in tapped]

    for entity in entities:
        if entity["confidence"] < CONFIRM_BELOW:
            logger.info(f"Low confidence ({entity['confidence']}) for {entity['field']}. Creating verification question.")

            q_text = f"I extracted '{entity['value']}' for {entity['field']}. Is this correct? (Reply Yes, or provide the correct value)"
            return {
                "current_question": {
                    "field": asked.get("field"),
                    "section": asked.get("section", ""),
                    "question_text": q_text,
                    "ui": "chips",
                    "options": [CONFIRM_CHIP],
                    "is_gate": asked.get("is_gate", False),
                    "missing_fields": asked.get("missing_fields", []),
                    "bullet_index": asked.get("bullet_index"),
                    "is_verification": True,
                    "verifying_field": entity["field"]
                },
            }

    logger.info("All extracted entities met confidence threshold.")
    groups = group_items(entities)
    extracted["entities"] = entities
    extracted["extracted_values"] = groups[0] if groups else {}

    extracted["extra_items"] = groups[1:]
    if groups[1:]:
        logger.info("The answer described %d further entr(y/ies).", len(groups) - 1)
    return {"extracted_entities": extracted}
