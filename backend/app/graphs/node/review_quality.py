"""One LLM pass over the bullets the user has already written, gated behind a single
yes/no so nobody gets interrogated for numbers they don't have.

analyze_gaps only sees emptiness: a bullet either exists or it doesn't. It cannot tell
that "Responsible for various tasks" says nothing, or that "Worked on 2 teams" holds a
digit that is not an achievement. This node judges the content instead.

Two modes in one node, the same shape as confirm_import and tailor_resume:

  1. Pick the weakest bullets, then ask ONCE whether they want to work on them.
  2. On "yes", queue those bullets as ordinary impact questions. On anything else,
     drop them and finish the resume.

Three separate "what was the number?" questions in a row, each answered "I don't have
one", is the shape users hate. One question they can decline costs nothing.
"""

import logging
import re
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, Field

from app.graphs.apply import impact_key
from app.graphs.node.generate_question import says_yes
from app.graphs.state import ResumeState
from app.utils.llm import get_openai_llm

logger = logging.getLogger(__name__)

MAX_IMPACT_QUESTIONS = 3

SECTIONS = ("experience", "projects")

GATE_SECTION = "impact_gate"

IMPROVE_CHIP = "Yes, let's add numbers"
                                                                                     
DECLINE_CHIP = "No, leave them as is"

class WeakBullet(BaseModel):
    field: str = Field(
        description="Container path of the bullet, exactly as listed, e.g. 'experience[0]' or 'projects[1]'."
    )
    bullet_index: int = Field(
        description="The number after the word 'bullet' on that line of the listing."
    )
    reason: str = Field(
        description="What this bullet is missing, in one short phrase — e.g. 'no measurable result', "
        "'does not say what was actually built', 'describes a duty rather than an achievement'."
    )

class QualityReview(BaseModel):
    weakest: List[WeakBullet] = Field(
        default_factory=list,
        description="The weakest bullets, most worth improving first. Empty if every bullet is already "
        "specific and carries a concrete result.",
    )

def list_bullets(resume: Dict[str, Any]) -> List[Tuple[str, int, str]]:
    """Every written bullet as (container path, index, text).

    The path vocabulary here is what the model is asked to hand back, and what
    merge_profile expects — one function so they cannot drift.
    """
    out: List[Tuple[str, int, str]] = []
    for section in SECTIONS:
        for i, item in enumerate(resume.get(section) or []):
            if not isinstance(item, dict):
                continue
            for j, bullet in enumerate(item.get("highlights") or []):
                if isinstance(bullet, str) and bullet.strip():
                    out.append((f"{section}[{i}]", j, bullet))
    return out

def usable_gaps(
    bullets: List[Tuple[str, int, str]],
    weakest: List[WeakBullet],
    skipped: List[str],
) -> List[Dict[str, Any]]:
    """Turn the model's picks into queue items, dropping anything that doesn't hold up.

    The model is free to invent an experience[7] that isn't there, repeat a bullet, or
    re-raise one the user already declined. Every pick is resolved back against the real
    profile and the bullet text is read from there, never from the model's echo — so a
    hallucinated index cannot put words into someone's resume.
    """
    known = {(field, index): text for field, index, text in bullets}
    already_asked = sum(1 for key in skipped if key.startswith("impact."))
    budget = MAX_IMPACT_QUESTIONS - already_asked

    gaps: List[Dict[str, Any]] = []
    seen = set()

    for pick in weakest:
        if len(gaps) >= budget:
            break

        key = (pick.field, pick.bullet_index)
        text = known.get(key)
        if text is None:
            logger.warning("Quality review named a bullet that does not exist: %s[%s]", *key)
            continue
        if key in seen or impact_key(pick.field, pick.bullet_index) in skipped:
            continue
        seen.add(key)

        gaps.append({
            "field": pick.field,
            "section": "impact",
            "kind": "impact",
            "missing_fields": ["metric"],
            "is_gate": False,
            "bullet_index": pick.bullet_index,
            "weak_bullet": text,
                                                                                       
            "reason": pick.reason.rstrip("."),
        })

    return gaps

def gate_question(gaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The opt-in question, with every affected line visible before a user commits."""
    count = len(gaps)
    noun = "bullet point" if count == 1 else "bullet points"
    examples = "\n\n".join(
        f"**Current bullet {index}:**\n\n> {gap.get('weak_bullet', '')}\n\n"
        f"Why it could be stronger: {gap.get('reason', 'it needs a clearer result')}."
        for index, gap in enumerate(gaps, start=1)
    )

    return {
        "field": GATE_SECTION,
        "section": GATE_SECTION,
        "question_text": (
            f"I found {count} {noun} that could be stronger.\n\n{examples}\n\n"
            "Would you like to add only the real outcomes you remember?"
        ),
        "ui": "chips",
        "options": [IMPROVE_CHIP, DECLINE_CHIP],
        "is_gate": False,
        "missing_fields": [],
        "bullet_index": None,
                                                                                       
        "pending_gaps": gaps,
    }

def wants_metrics(answer: str) -> bool:
    """Did they take the gate?

    Anything unclear counts as no — declining costs the user one polished-but-unquantified
    bullet, while a false yes costs three questions they already said they didn't want.
    Shares says_yes with the section gates so "yes" means one thing across the app.
    """
    return says_yes(answer)

def review_quality(state: ResumeState) -> Dict[str, Any]:
    """Ask whether the weak bullets are worth working on — then queue them, or don't."""
    pending = state.get("current_question") or {}
    answer = state.get("latest_answer")

    if answer and pending.get("section") == GATE_SECTION:
        done: Dict[str, Any] = {"latest_answer": None, "current_question": None}

        if not wants_metrics(answer):
            logger.info("User declined the metric questions.")
            return done

        gaps = pending.get("pending_gaps") or []
        logger.info("User opted in to %d metric question(s).", len(gaps))
        return {**done, "question_queue": gaps}

    return _find_weak_bullets(state)

def _find_weak_bullets(state: ResumeState) -> Dict[str, Any]:
    resume = state.get("master_profile", {})
    if hasattr(resume, "model_dump"):
        resume = resume.model_dump()

    skipped = list(state.get("skipped") or [])
                                                                                            
    done: Dict[str, Any] = {"quality_reviewed": True, "current_question": None}

    bullets = list_bullets(resume)
    already_asked = sum(1 for key in skipped if key.startswith("impact."))
    if not bullets or already_asked >= MAX_IMPACT_QUESTIONS:
        return done

    listing = "\n".join(f"{field} bullet {index}: {text}" for field, index, text in bullets)

    prompt = f"""
    These are the bullet points on someone's resume.

    {listing}

    Pick at most {MAX_IMPACT_QUESTIONS - already_asked} that would gain the most from one
    follow-up question, weakest first. A bullet is weak when it describes a duty rather
    than an achievement, is vague about what was actually built or changed, or claims an
    outcome with no result attached. A number alone does not make a bullet strong —
    "worked on 2 teams" is still a duty.

    Return the paths and indexes exactly as listed above. If every bullet is already
    specific and carries a real result, return nothing — a needless question costs the
    user more than a marginal bullet gains.
    """

    try:
        review: QualityReview = get_openai_llm().with_structured_output(
            QualityReview, method="function_calling"
        ).invoke(prompt)
    except Exception as e:
                                                                                           
        logger.error("Quality review failed, moving on: %r", e)
        return done

    gaps = usable_gaps(bullets, review.weakest, skipped)
    logger.info("Quality review found %d weak bullet(s) out of %d.", len(gaps), len(bullets))

    if not gaps:
        return done
    return {**done, "current_question": gate_question(gaps)}

if __name__ == "__main__":
    profile = {
        "experience": [{"highlights": ["Managed social media", "Cut build time 40%"]}],
        "projects": [{"highlights": ["Built a parser"]}],
        "education": [{"institution": "IIT"}],
    }

    bullets = list_bullets(profile)
    assert bullets == [
        ("experience[0]", 0, "Managed social media"),
        ("experience[0]", 1, "Cut build time 40%"),
        ("projects[0]", 0, "Built a parser"),
    ], bullets
    assert list_bullets({"experience": [{"highlights": ["", "  "]}]}) == [], "blank bullets aren't bullets"
    assert list_bullets({}) == []

    def pick(field, index, reason="no measurable result"):
        return WeakBullet(field=field, bullet_index=index, reason=reason)

    gaps = usable_gaps(bullets, [pick("experience[0]", 0)], [])
    assert len(gaps) == 1, gaps
    assert gaps[0]["section"] == "impact" and gaps[0]["kind"] == "impact"
    assert gaps[0]["bullet_index"] == 0
    assert gaps[0]["weak_bullet"] == "Managed social media"
    assert gaps[0]["reason"] == "no measurable result"

    assert usable_gaps(bullets, [pick("experience[9]", 0)], []) == []
    assert usable_gaps(bullets, [pick("experience[0]", 7)], []) == []
    assert usable_gaps(bullets, [pick("nonsense", 0)], []) == []

    assert len(usable_gaps(bullets, [pick("experience[0]", 0), pick("experience[0]", 0)], [])) == 1
    assert usable_gaps(bullets, [pick("experience[0]", 0)], [impact_key("experience[0]", 0)]) == []

    many = [pick("experience[0]", 0), pick("experience[0]", 1), pick("projects[0]", 0)]
    assert len(usable_gaps(bullets, many, [])) == MAX_IMPACT_QUESTIONS
    assert len(usable_gaps(bullets, many, ["impact.experience[1].0"])) == MAX_IMPACT_QUESTIONS - 1
    assert usable_gaps(bullets, many, [f"impact.x[{i}].0" for i in range(MAX_IMPACT_QUESTIONS)]) == []

    assert usable_gaps(bullets, [], []) == []

    line = f"{bullets[1][0]} bullet {bullets[1][1]}: {bullets[1][2]}"
    assert not re.match(r"^\w+\[\d+\]\[\d+\]", line), line
    assert line.startswith("experience[0] bullet 1:"), line

    found = usable_gaps(bullets, many, [])
    gate = gate_question(found)
    assert gate["ui"] == "chips" and gate["options"] == [IMPROVE_CHIP, DECLINE_CHIP]
    assert gate["section"] == GATE_SECTION, "the router matches on this to send the reply back here"
    assert gate["pending_gaps"] == found, "the picks ride on the question, not a new state field"
    assert "> Managed social media" in gate["question_text"], "the gate must name the exact bullet"
    assert "Why it could be stronger: no measurable result." in gate["question_text"]
    assert "1 bullet points" not in gate_question(found[:1])["question_text"], "count must read naturally"

    took = review_quality({"current_question": gate, "latest_answer": IMPROVE_CHIP})
    assert took["question_queue"] == found
    assert took["current_question"] is None and took["latest_answer"] is None

    for yes in (IMPROVE_CHIP, "yes", "Yes please", "sure", "yeah lets do it", "OK"):
        assert wants_metrics(yes), yes

    for no in (DECLINE_CHIP, "no", "not really", "skip", "", "I don't have numbers"):
        assert not wants_metrics(no), no

    declined = review_quality({"current_question": gate, "latest_answer": DECLINE_CHIP})
    assert "question_queue" not in declined, "declining must not queue anything"
    assert declined["current_question"] is None

    assert review_quality({"master_profile": {}}) == {"quality_reviewed": True, "current_question": None}
    spent = {"master_profile": profile, "skipped": [f"impact.x[{i}].0" for i in range(MAX_IMPACT_QUESTIONS)]}
    assert review_quality(spent)["current_question"] is None, "no budget must mean no LLM call"

    print("review_quality ok")
