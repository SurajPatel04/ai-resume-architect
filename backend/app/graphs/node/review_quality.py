"""One LLM pass over the bullets the user has already written, gated behind a single yes/no so
nobody gets interrogated for numbers they don't have.
"""

import logging
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, Field

from app.graphs.apply import apply_extraction, impact_key, read_slot, slot_parts
from app.graphs.node.enhance_resume import numbers_in
from app.graphs.node.generate_question import current_item, says_yes
from app.graphs.state import Resume, ResumeState
from app.graphs.prompts import WEAK_BULLETS
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
    rewrite: str = Field(
        default="",
        description="This bullet rewritten as it would read WITH the missing figure in it, using "
        "{} to mark the one spot the number goes — including its unit right after the braces. "
        "e.g. 'Integrated the Razorpay payment gateway, lifting transaction success rate to {}%, "
        "with custom backend logic for discount coupons.' Keep every fact the original states; "
        "you are adding one measurement to it, not writing a new bullet. Exactly one {}, no other "
        "braces, and NEVER a digit of your own — the candidate fills the blank. Leave empty when "
        "no single figure would make this bullet stronger.",
    )

class QualityReview(BaseModel):
    weakest: List[WeakBullet] = Field(
        default_factory=list,
        description="The weakest bullets, most worth improving first. Empty if every bullet is already "
        "specific and carries a concrete result.",
    )

def list_bullets(resume: Dict[str, Any]) -> List[Tuple[str, int, str]]:
    """Every written bullet as (container path, index, text)."""
    out: List[Tuple[str, int, str]] = []
    for section in SECTIONS:
        for i, item in enumerate(resume.get(section) or []):
            if not isinstance(item, dict):
                continue
            for j, bullet in enumerate(item.get("highlights") or []):
                if isinstance(bullet, str) and bullet.strip():
                    out.append((f"{section}[{i}]", j, bullet))
    return out

SECTION_LABELS = {"experience": "Experience", "projects": "Projects"}

def usable_rewrite(original: str, rewrite: str) -> str:
    """The proposed bullet-with-a-blank, or nothing if it cannot be trusted."""
    rewrite = (rewrite or "").strip()
    if not rewrite:
        return ""

    if slot_parts(rewrite) is None:
        logger.warning("Dropped a rewrite that was not one fillable bullet: %r", rewrite)
        return ""

    if not numbers_in(rewrite) <= numbers_in(original):
        logger.warning("Dropped a rewrite that invented a figure: %r", rewrite)
        return ""

    return rewrite

def entry_title(resume: Dict[str, Any], field: str) -> str:
    """Which entry a bullet sits on, in the words the user would recognise it by."""
    section, _, _ = (field or "").partition("[")
    label = SECTION_LABELS.get(section, section.title())

    item = current_item(resume, field)
    if section == "projects":
        name = item.get("name")
        return f"{label}: {name}" if name else label

    role, company = item.get("position"), item.get("company")
    if role and company:
        return f"{label}: {role} at {company}"
    named = role or company
    return f"{label}: {named}" if named else label

def preview(rewrite: str) -> str:
    """The proposed bullet as prose, with the blank shown as a blank."""
    parts = slot_parts(rewrite or "")
    return f"{parts[0]}___{parts[1]}" if parts else ""

def usable_gaps(
    bullets: List[Tuple[str, int, str]],
    weakest: List[WeakBullet],
    skipped: List[str],
    resume: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """Turn the model's picks into queue items, dropping anything that doesn't hold up."""
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

            "entry": entry_title(resume or {}, pick.field),

            "rewrite": usable_rewrite(text, pick.rewrite),
        })

    return gaps

def gate_card(index: int, gap: Dict[str, Any]) -> str:
    """One weak bullet as it appears in the gate: where it lives, what it says, what it lacks."""
    entry = gap.get("entry")
    heading = f"**Current bullet {index} — {entry}**" if entry else f"**Current bullet {index}:**"

    lines = [
        heading,
        f"> {gap.get('weak_bullet', '')}",
        f"Why it could be stronger: {gap.get('reason', 'it needs a clearer result')}.",
    ]

    shown = preview(gap.get("rewrite", ""))
    if shown:
        lines.append(f"Could read:\n\n> {shown}")

    return "\n\n".join(lines)

def gate_meta(gaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """What the front end needs to draw the same cards with the blanks typeable."""
    return {"gaps": [
        {
            "label": f"Current bullet {index} — {gap['entry']}" if gap.get("entry")
                     else f"Current bullet {index}",
            "original": gap.get("weak_bullet", ""),
            "reason": gap.get("reason", "it needs a clearer result"),
            "template": gap.get("rewrite", ""),
        }
        for index, gap in enumerate(gaps, start=1)
    ]}

def gate_question(gaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The opt-in question, with every affected line visible before a user commits."""
    count = len(gaps)
    noun = "bullet point" if count == 1 else "bullet points"
    fillable = [gap for gap in gaps if gap.get("rewrite")]

    if fillable:
        # Cards are drawn from `meta`; repeating them here would print each twice.
        text = (
            f"I found {count} {noun} that could be stronger. I've drafted how each could "
            "read — fill in any figure you actually remember and leave the rest blank."
        )
    else:
        examples = "\n\n".join(gate_card(index, gap) for index, gap in enumerate(gaps, start=1))
        text = (
            f"I found {count} {noun} that could be stronger.\n\n{examples}\n\n"
            "Would you like to add only the real outcomes you remember?"
        )

    return {
        "field": GATE_SECTION,
        "section": GATE_SECTION,
        "question_text": text,
        "ui": "impact_gate" if fillable else "chips",
        "options": [DECLINE_CHIP] if fillable else [IMPROVE_CHIP, DECLINE_CHIP],
        "is_gate": False,
        "missing_fields": [],
        "bullet_index": None,

        "meta": gate_meta(gaps) if fillable else None,

        "pending_gaps": gaps,
    }

def filled_lines(gaps: List[Dict[str, Any]], answer: str) -> List[Dict[str, Any]]:
    """The gaps whose blank the user actually filled in, paired with the finished line."""
    lines = [line.strip() for line in (answer or "").splitlines() if line.strip()]

    out: List[Dict[str, Any]] = []
    taken: set = set()
    for gap in gaps:
        template = gap.get("rewrite") or ""
        if not template:
            continue
        for index, line in enumerate(lines):
            # Each line spends itself on one bullet, so twins cannot both claim it.
            if index in taken:
                continue
            figure = read_slot(template, line)
            if figure:
                taken.add(index)
                out.append({**gap, "figure": figure, "filled": line})
                break

    return out

def apply_filled(resume: Dict[str, Any], filled: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Every filled-in bullet written onto the profile, or the profile unchanged."""
    if not filled:
        return resume

    candidate = resume
    for gap in filled:
        candidate = apply_extraction(
            candidate, gap["field"], {"metric": gap["figure"]},
            bullet_index=gap.get("bullet_index"), template=gap.get("rewrite"),
        )

    try:
        return Resume.model_validate(candidate).model_dump()
    except Exception as e:
        logger.warning("Filled-in bullets did not validate, keeping the resume as it was: %r", e)
        return resume

def wants_metrics(answer: str) -> bool:
    """Did they take the gate?"""
    return says_yes(answer)

def review_quality(state: ResumeState) -> Dict[str, Any]:
    """Ask whether the weak bullets are worth working on — then queue them, or don't."""
    pending = state.get("current_question") or {}
    answer = state.get("latest_answer")

    if answer and pending.get("section") == GATE_SECTION:
        done: Dict[str, Any] = {"latest_answer": None, "current_question": None}
        gaps = pending.get("pending_gaps") or []

        filled = filled_lines(gaps, answer)
        if filled:
            resume = state.get("master_profile", {})
            if hasattr(resume, "model_dump"):
                resume = resume.model_dump()

            logger.info("User filled in %d of %d bullet(s) on the card.", len(filled), len(gaps))

            # Every bullet on the card is retired: a blank box is an answer too.
            skipped = list(state.get("skipped") or [])
            skipped += [impact_key(g["field"], g.get("bullet_index")) for g in gaps]

            return {**done, "master_profile": apply_filled(resume, filled), "skipped": skipped}

        if not wants_metrics(answer):
            logger.info("User declined the metric questions.")
            return done

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

    listing = "\n".join(
        f"{field} ({entry_title(resume, field)}) bullet {index}: {text}"
        for field, index, text in bullets
    )

    prompt = WEAK_BULLETS.format(
        listing=listing, budget=MAX_IMPACT_QUESTIONS - already_asked
    )

    try:
        review: QualityReview = get_openai_llm().with_structured_output(
            QualityReview, method="function_calling"
        ).invoke(prompt)
    except Exception as e:

        logger.error("Quality review failed, moving on: %r", e)
        return done

    gaps = usable_gaps(bullets, review.weakest, skipped, resume)
    logger.info("Quality review found %d weak bullet(s) out of %d.", len(gaps), len(bullets))

    if not gaps:
        return done
    return {**done, "current_question": gate_question(gaps)}
