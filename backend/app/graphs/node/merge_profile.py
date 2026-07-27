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
    """Add entries the same answer described beyond the one that was asked about.

    A question is about one entry, so `entities` describes one entry — and someone who
    answers "MCA at Amity 2024-2026 AND BSc from Lucknow Christian 2021-2024" had the
    second degree silently dropped, with nothing later in the interview to recover it.

    Each entry is validated on its own and discarded if it does not hold up, so the
    profile this returns is still schema-valid without being re-validated: the caller has
    already validated everything else, and every dict added here is a model_dump.
    """
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
    """The question queue after an answer has landed.

    Popping unconditionally is what made the interview wander. A question that asked for
    an institution AND an area, answered with just "Amity University", dropped the gap
    anyway — analyze_gaps rediscovered the missing area two turns later and re-queued it
    behind every section asked in between, so education was abandoned half-done and
    returned to three questions afterwards. A half-answered gap stays at the head, asking
    only for what is still missing.

    A gate still clears the whole queue: saying yes opens an entry whose fields nothing
    has planned for yet.
    """
    if question.get("is_gate"):
        return []

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
    """
    Deterministically merges the extracted_entities into master_profile.
    Only runs if validation succeeds.
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
            apply_extraction(resume, target_field, extracted_values, bullet_index)
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

if __name__ == "__main__":
    EDU_GAP = {"field": "education[0]", "section": "education", "kind": "required",
               "is_gate": False, "missing_fields": ["institution", "area"],
               "reason": "Education entry 1 is missing: institution, area."}
    QUEUE = [EDU_GAP, {"field": "projects[0]", "section": "projects", "is_gate": True},
             {"field": "target_role", "section": "target_role", "is_gate": True}]

    def profile(**education):
        return Resume.model_validate({"education": [education]}).model_dump()

    half = advance(QUEUE, EDU_GAP, profile(institution="Amity University", area=""))
    assert half[0]["field"] == "education[0]", "a half-answered gap must not be abandoned"
    assert half[0]["missing_fields"] == ["area"], half[0]["missing_fields"]
    assert "area" in half[0]["reason"] and "institution" not in half[0]["reason"],\
        "the re-ask must not demand what was just given"
    assert [g["field"] for g in half[1:]] == [g["field"] for g in QUEUE[1:]], "nothing else moves"

    done_gap = advance(QUEUE, EDU_GAP, profile(institution="Amity University", area="MCA"))
    assert [g["field"] for g in done_gap] == ["projects[0]", "target_role"]

    assert advance(QUEUE, EDU_GAP, profile(institution="", area="")) == QUEUE[1:]
                                                                     
    only_area = {**EDU_GAP, "missing_fields": ["area"]}
    assert advance(QUEUE, only_area, profile(institution="Amity University", area="")) == QUEUE[1:]

    gate = {"field": "education[0]", "section": "education", "is_gate": True,
            "missing_fields": ["institution", "area"]}
    assert advance(QUEUE, gate, profile(institution="", area="")) == []

    impact = {"field": "experience[0]", "section": "impact", "is_gate": False,
              "missing_fields": ["metric"], "bullet_index": 0}
    experience = Resume.model_validate({"experience": [{"highlights": ["Did a thing"]}]}).model_dump()
    assert advance(QUEUE, impact, experience) == QUEUE[1:], "an impact gap is answered once"
    invented = {"field": "experience[0]", "section": "experience", "is_gate": False,
                "missing_fields": ["scale", "stack"]}
    assert advance(QUEUE, invented, experience) == QUEUE[1:]

    skills = {"field": "skills", "section": "skills", "is_gate": False, "missing_fields": ["skills"]}
    assert advance(QUEUE, skills, Resume().model_dump()) == QUEUE[1:]

    assert advance([], EDU_GAP, profile(institution="X", area="")) == [], "no queue, nothing to advance"

    first = profile(institution="Amity University", area="Machine Learning",
                    study_type="MCA", start_date="2024", end_date="2026")
    both = append_items(first, "education", [
        {"institution": "Lucknow Christian College", "study_type": "BSc",
         "start_date": "2021", "end_date": "2024"},
    ])
    assert len(both["education"]) == 2, both["education"]
    assert both["education"][1]["institution"] == "Lucknow Christian College"
    assert both["education"][1]["end_date"] == "2024"
    assert both["education"][0] == first["education"][0], "the answered entry must not move"
                                                                                       
    assert Resume.model_validate(both).education[1].study_type == "BSc"
    assert first["education"] == profile(institution="Amity University", area="Machine Learning",
                                         study_type="MCA", start_date="2024",
                                         end_date="2026")["education"], "must not mutate the input"

    PASTED = ("• Architected an AI video pipeline (React, FastAPI, MongoDB).\n"
              "• Engineered a self-healing generation loop with Vision QA.")
    projects = Resume.model_validate({"projects": [{"name": "InsightFlow"}]}).model_dump()
    two = append_items(projects, "projects", [
        {"name": "AI Manim Video Generator", "url": "github.com/SurajPatel04/manimVideoGenerate",
         "highlights": PASTED},
    ])
    assert [p["name"] for p in two["projects"]] == ["InsightFlow", "AI Manim Video Generator"],\
        two["projects"]
    assert two["projects"][1]["highlights"] == [
        "Architected an AI video pipeline (React, FastAPI, MongoDB).",
        "Engineered a self-healing generation loop with Vision QA.",
    ], two["projects"][1]["highlights"]
    assert Resume.model_validate(two).projects[1].url.endswith("manimVideoGenerate")

    assert append_items(first, "education", [{"institution": ["not", "a", "string"]}]) is first
    assert append_items(first, "education", [{}, {"institution": ""}]) is first
    assert append_items(first, "education", []) is first
                                                                       
    assert append_items(first, "skills", [{"name": "x"}]) is first
    assert append_items(first, "basics", [{"phone": "1"}]) is first
                                                       
    flood = append_items(first, "education", [{"institution": f"U{i}"} for i in range(20)])
    assert len(flood["education"]) == 1 + MAX_EXTRA_ITEMS, len(flood["education"])

    landed = merge_profile({
        "current_question": {**EDU_GAP, "question_text": "Which institution and area?"},
        "latest_answer": "MCA Amity 2024-2026 and BSc Lucknow Christian 2021-2024",
        "question_queue": list(QUEUE),
        "master_profile": Resume().model_dump(),
        "extracted_entities": {
            "extracted_values": {"institution": "Amity University", "area": "Machine Learning"},
            "entities": [], "extra_items": [{"institution": "Lucknow Christian College"}],
        },
    })
    assert [e["institution"] for e in landed["master_profile"]["education"]] ==\
        ["Amity University", "Lucknow Christian College"], landed["master_profile"]["education"]
                                                                                           
    assert landed["question_queue"] == [], landed["question_queue"]

    print("merge_profile ok")
