"""Turn the ATS gap report into one question the user can actually answer."""

import copy
import logging
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, Field

from app.graphs.state import Resume, ResumeState
from app.graphs.node.generate_question import says_yes
from app.graphs.prompts import CLAIMED_SKILLS
from app.utils.llm import get_openai_llm

logger = logging.getLogger(__name__)

GATE_SECTION = "skill_gap"

MAX_OFFERED = 6

NONE_CHIP = "None of these"
UPDATE_CHIP = "Yes, update my resume"
KEEP_CHIP = "No, keep it as is"

class ClaimedSkill(BaseModel):
    keyword: str = Field(
        description="Exactly one of the offered keywords, copied verbatim from the list."
    )
    category: str = Field(
        description="Which of the resume's existing skill categories this belongs under. "
        "Copy one of the category names given. Only name a new one if none of them fit."
    )

class ClaimedSkills(BaseModel):
    skills: List[ClaimedSkill] = Field(
        default_factory=list,
        description="Only the offered keywords the user actually said they have. Empty if they said none, "
        "were vague, or talked about something else. Never include a keyword they did not claim.",
    )

def human_list(items: List[str]) -> str:
    """'a, b and c' — reads as a sentence, unlike a bare comma join."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"

def kept_placements(offered: List[str], claims: List[ClaimedSkill]) -> List[Tuple[str, str]]:
    """(keyword, category) pairs, restricted to what was actually offered."""
    allowed = {o.strip().lower(): o for o in offered}
    out: List[Tuple[str, str]] = []
    seen = set()

    for claim in claims:
        canonical = allowed.get((claim.keyword or "").strip().lower())
        if canonical is None:
            logger.warning("Ignoring a skill that was never offered: %r", claim.keyword)
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append((canonical, (claim.category or "").strip()))

    return out

def add_skills(resume: Dict[str, Any], placements: List[Tuple[str, str]]) -> Dict[str, Any]:
    """Append each keyword under its category, creating one only when nothing fits."""
    r = copy.deepcopy(resume)
    categories = r.setdefault("skills", [])
    by_name = {(c.get("name") or "").strip().lower(): c for c in categories if isinstance(c, dict)}

    for keyword, category in placements:
        target = by_name.get(category.lower())
        if target is None:
            target = {"name": category or "Additional Skills", "keywords": []}
            categories.append(target)
            by_name[target["name"].strip().lower()] = target

        existing = target.setdefault("keywords", [])
        if keyword.lower() not in {str(k).lower() for k in existing}:
            existing.append(keyword)

    return r

def _ask(state: ResumeState) -> Dict[str, Any]:
    """Ask permission before offering any JD-derived skills to add."""
    feedback = state.get("ats_feedback") or {}
    missing = [k.strip() for k in (feedback.get("missing_keywords") or []) if k and k.strip()]
    missing = missing[:MAX_OFFERED]

    done: Dict[str, Any] = {"skill_gap_asked": True, "current_question": None}
    if not missing:
        return done

    logger.info("Asking permission to improve ATS alignment with %d missing keyword(s).", len(missing))
    return {
        "current_question": {
            "field": "skills",
            "section": GATE_SECTION,
            "question_text": (
                f"This resume is missing some skills from the job description, including {human_list(missing)}. "
                "Would you like to update it for this job? I will only add skills you confirm you have."
            ),
            "ui": "chips",
            "options": [UPDATE_CHIP, KEEP_CHIP],
            "is_gate": False,
            "missing_fields": ["skills"],
            "bullet_index": None,

            "offered": missing,
            "step": "confirm_update",
        },
    }

def _ask_claims(state: ResumeState, offered: List[str]) -> Dict[str, Any]:
    """After consent, ask which JD skills the candidate genuinely has."""
    return {
        "skill_gap_asked": True,
        "current_question": {
            "field": "skills",
            "section": GATE_SECTION,
            "question_text": (
                f"Which of these do you actually have: {human_list(offered)}? "
                "Type the ones you use — I will add only those."
            ),
            "ui": "chips",
            "options": [NONE_CHIP],
            "is_gate": False,
            "missing_fields": ["skills"],
            "bullet_index": None,
            "offered": offered,
            "step": "claim_skills",
        },
    }

def _apply(state: ResumeState, pending: Dict[str, Any], answer: str) -> Dict[str, Any]:
    done: Dict[str, Any] = {"latest_answer": None, "current_question": None}
    offered = pending.get("offered") or []

    if not offered or answer.strip() == NONE_CHIP:
        return done

    resume = state.get("master_profile", {})
    if hasattr(resume, "model_dump"):
        resume = resume.model_dump()

    categories = [c.get("name", "") for c in (resume.get("skills") or []) if isinstance(c, dict)]

    prompt = CLAIMED_SKILLS.format(
        offered=", ".join(offered),
        answer=answer,
        categories=", ".join(categories) or "(none yet)",
    )

    try:
        claimed: ClaimedSkills = get_openai_llm().with_structured_output(
            ClaimedSkills, method="function_calling"
        ).invoke(prompt)
    except Exception as e:
        logger.error("Could not read the skill answer, adding nothing: %r", e)
        return done

    placements = kept_placements(offered, claimed.skills)
    if not placements:
        logger.info("No offered skills were claimed.")
        return done

    logger.info("Adding claimed skills: %s", ", ".join(k for k, _ in placements))

    try:
        updated = Resume.model_validate(add_skills(resume, placements)).model_dump()
    except Exception as e:
        logger.warning("Skill additions failed validation, discarding: %r", e)
        return done

    result: Dict[str, Any] = {**done, "master_profile": updated}

    generated = dict(state.get("generated_resumes") or {})
    tailored = generated.get("tailored")
    if tailored is not None:
        t = tailored.model_dump() if hasattr(tailored, "model_dump") else tailored
        try:
            generated["tailored"] = Resume.model_validate(add_skills(t, placements)).model_dump()
            result["generated_resumes"] = generated
        except Exception as e:
            logger.warning("Could not mirror the skills onto the tailored resume: %r", e)

    return result

def skill_gap(state: ResumeState) -> Dict[str, Any]:
    """Ask about the job's missing keywords, then add back only what the user claims."""
    pending = state.get("current_question") or {}
    answer = state.get("latest_answer")

    if answer and pending.get("section") == GATE_SECTION and pending.get("step") == "confirm_update":
        if says_yes(answer):
            return _ask_claims(state, pending.get("offered") or [])
        return {"skill_gap_asked": True, "latest_answer": None, "current_question": None}

    if answer and pending.get("section") == GATE_SECTION:
        return _apply(state, pending, answer)

    return _ask(state)
