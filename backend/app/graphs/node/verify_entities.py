import logging
from typing import Any, Dict, List
from app.graphs.apply import LIST_FIELDS
from app.graphs.node.generate_question import is_affirmation
from app.graphs.state import ResumeState

logger = logging.getLogger(__name__)

MULTI_VALUE = LIST_FIELDS | {"skills"}

def collect_values(entities: List[Dict[str, Any]]) -> Dict[str, Any]:
    """entities -> {field: value}, keeping every answer when a field is named twice.

    A dict comprehension keyed by field is what lost seven of eight skills: asked for
    "skills", the extractor returns one entity per skill — all named "skills" — and the
    last one silently overwrote the rest. Multi-value fields collect into a list, which
    is exactly what apply_extraction expects; anything else keeps the first answer,
    because overwriting a scalar with a later guess is how the wrong company name wins.
    """
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
    """Entities split into the entries they describe, the one that was asked about first.

    A question is about one entry; people answer with two projects or two degrees in one
    message. The extractor tags each field with the entry it belongs to, and this is where
    that flat list becomes one {field: value} dict per entry — the first for the item the
    question was about, the rest for merge_profile to append.

    An entity with no tag at all is entry zero, so anything that predates this (or an
    extractor that ignores the field) behaves exactly as it always did.
    """
    by_item: Dict[int, List[Dict[str, Any]]] = {}

    for entity in entities:
        try:
            index = max(0, int(entity.get("item") or 0))
        except (TypeError, ValueError):
            index = 0
        by_item.setdefault(index, []).append(entity)

    return [collect_values(by_item[key]) for key in sorted(by_item)]

CONFIRM_BELOW = 0.65

def verify_entities(state: ResumeState) -> Dict[str, Any]:
    """
    Checks the confidence of extracted entities.
    Anything below CONFIRM_BELOW is put straight back to the user; the rest is converted
    to extracted_values, carrying its confidence forward for the planner to weigh.
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
                    "options": ["Yes, that's right"],
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
                    "options": ["Yes, that's right"],
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

if __name__ == "__main__":
    def run(entities, question=None):
        return verify_entities({
            "current_question": question or {"field": "projects[0]", "section": "projects"},
            "extracted_entities": {"is_skip": False, "entities": list(entities)},
        })["extracted_entities"]

    def entity(field, value, confidence=1.0, item=0):
        return {"field": field, "value": value, "confidence": confidence, "item": item}

    GATE = {"field": "projects[0]", "section": "projects", "is_gate": True,
            "missing_fields": ["name", "highlights"]}

    assert run([entity("name", "Yes")], GATE)["extracted_values"] == {}
    for tap in ("Yes", "yeah", " OK ", "Sure.", "yes please", "Correct"):
        assert run([entity("name", tap)], GATE)["extracted_values"] == {}, tap

    assert run([entity("name", "Yes"), entity("highlights", "Built a parser")], GATE)\
        ["extracted_values"] == {"highlights": "Built a parser"}
    assert run([entity("company", "Okta")], GATE)["extracted_values"] == {"company": "Okta"}
    assert run([entity("name", "Yes")])["extracted_values"] == {"name": "Yes"},\
        "outside a gate, 'Yes' could genuinely be what they wrote"

    assert run([entity("company", "Acme")])["extracted_values"] == {"company": "Acme"}
    shaky = verify_entities({
        "current_question": {"field": "basics", "section": "basics"},
        "extracted_entities": {"is_skip": False, "entities": [entity("phone", "98399", 0.4)]},
    })
    assert shaky["current_question"]["is_verification"] is True
    assert "extracted_values" not in shaky.get("extracted_entities", {})

    skipped = verify_entities({"extracted_entities": {"is_skip": True, "entities": [entity("name", "x")]}})
    assert "extracted_values" not in skipped["extracted_entities"]
    assert skipped["extracted_entities"]["is_skip"] is True

    TAPPED = ["Python", "JavaScript", "Node.js", "Express", "HTML", "MongoDB", "SQL", "TypeScript"]
    many = collect_values([entity("skills", s) for s in TAPPED])
    assert many["skills"] == TAPPED, many

    from app.graphs.apply import apply_extraction
    assert apply_extraction({"skills": []}, "skills", many)["skills"][0]["keywords"] == TAPPED

    one = collect_values([entity("skills", ", ".join(TAPPED))])
    assert apply_extraction({"skills": []}, "skills", one)["skills"][0]["keywords"] == TAPPED

    bullets = collect_values([entity("highlights", "Built the parser"),
                              entity("highlights", "Cut build time 40%")])
    assert bullets["highlights"] == ["Built the parser", "Cut build time 40%"]
                                                                             
    assert collect_values([entity("highlights", ["a", "b"]), entity("highlights", "c")])\
        == {"highlights": ["a", "b", "c"]}

    assert collect_values([entity("company", "Acme"), entity("company", "Acme Corp")])\
        == {"company": "Acme"}
    assert collect_values([]) == {}

    assert run([entity("skills", s) for s in TAPPED])["extracted_values"]["skills"] == TAPPED

    PASTED = [
        entity("name", "InsightFlow", item=0),
        entity("highlights", "Engineered a RAG platform", item=0),
        entity("url", "github.com/SurajPatel04/ai-multimedia-rag-app", item=0),
        entity("name", "AI Manim Video Generator", item=1),
        entity("highlights", "Architected an AI video pipeline", item=1),
    ]
    two = run(PASTED)
    assert two["extracted_values"]["name"] == "InsightFlow", two["extracted_values"]
    assert two["extra_items"] == [{"name": "AI Manim Video Generator",
                                   "highlights": "Architected an AI video pipeline"}], two["extra_items"]

    grouped = group_items([
        entity("highlights", "One", item=0), entity("highlights", "Two", item=0),
        entity("company", "Acme", item=1), entity("company", "Acme Corp", item=1),
    ])
    assert grouped == [{"highlights": ["One", "Two"]}, {"company": "Acme"}], grouped

    assert group_items([{"field": "company", "value": "Acme", "confidence": 1.0}])\
        == [{"company": "Acme"}]
    assert run([{"field": "company", "value": "Acme", "confidence": 1.0}])["extra_items"] == []
    assert group_items([]) == []
                                                                
    assert group_items([entity("company", "Acme", item="x"), entity("position", "Eng", item=-3)])\
        == [{"company": "Acme", "position": "Eng"}]
                                                                           
    assert group_items([entity("name", "B", item=5), entity("name", "A", item=2)])\
        == [{"name": "A"}, {"name": "B"}]

    print("verify_entities ok")
