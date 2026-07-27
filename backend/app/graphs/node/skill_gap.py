"""Turn the ATS gap report into one question the user can actually answer.

score_ats already works out which of the job's keywords are missing from the resume.
Until now that list was printed once at the end and nothing came of it — yet some of
those "missing" skills are ones the candidate genuinely has and never wrote down.

Asked once, only about keywords the job itself named, and only ever adding back a
keyword the user claimed. Answering re-scores, so the number they are looking at
reflects what they just told us.
"""

import copy
import logging
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, Field

from app.graphs.state import Resume, ResumeState
from app.graphs.node.generate_question import says_yes
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
    """(keyword, category) pairs, restricted to what was actually offered.

    The keyword is taken from `offered`, never from the model's echo — so a rewording,
    a hallucination, or a skill the job never asked for cannot reach the resume. This is
    the whole safety property of the node: it can only ever put back what it offered.
    """
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
    """Append each keyword under its category, creating one only when nothing fits.

    Not apply_extraction's `skills` branch: that appends everything to the first
    category, which files Kubernetes under "Languages" on the rendered PDF.
    """
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

    prompt = f"""
    We asked the candidate which of these skills, taken from a job description, they
    actually have:

    {", ".join(offered)}

    THEIR REPLY: "{answer}"

    Return only the ones they clearly said they have. If they were vague, said no, or
    talked about something else, return nothing — claiming a skill someone does not have
    is worse for them than leaving it off.

    File each under one of their existing skill categories: {", ".join(categories) or "(none yet)"}
    """

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

if __name__ == "__main__":
    assert human_list([]) == ""
    assert human_list(["Kubernetes"]) == "Kubernetes"
    assert human_list(["Kubernetes", "Terraform"]) == "Kubernetes and Terraform"
    assert human_list(["a", "b", "c"]) == "a, b and c"

    OFFERED = ["Kubernetes", "Terraform", "gRPC"]

    def claim(keyword, category="Tools & DevOps"):
        return ClaimedSkill(keyword=keyword, category=category)

    assert kept_placements(OFFERED, [claim("kubernetes")]) == [("Kubernetes", "Tools & DevOps")]
    assert kept_placements(OFFERED, [claim("  TERRAFORM ")]) == [("Terraform", "Tools & DevOps")]

    assert kept_placements(OFFERED, [claim("Rust")]) == [], "a skill the job never asked for"
    assert kept_placements(OFFERED, [claim("")]) == []
    assert kept_placements(OFFERED, [claim("Kubernetes"), claim("Kubernetes")]) ==\
        [("Kubernetes", "Tools & DevOps")], "duplicates collapse"

    profile = {"skills": [
        {"name": "Languages", "keywords": ["Python"]},
        {"name": "Tools & DevOps", "keywords": ["Docker"]},
    ]}
    r = add_skills(profile, [("Kubernetes", "tools & devops")])
    assert len(r["skills"]) == 2, "an existing category must not be duplicated"
    assert r["skills"][1]["keywords"] == ["Docker", "Kubernetes"]
    assert r["skills"][0]["keywords"] == ["Python"], "Kubernetes must not land under Languages"
    assert profile["skills"][1]["keywords"] == ["Docker"], "must not mutate the input"

    r = add_skills(profile, [("gRPC", "Protocols")])
    assert r["skills"][-1] == {"name": "Protocols", "keywords": ["gRPC"]}
    assert add_skills({}, [("gRPC", "")])["skills"] == [{"name": "Additional Skills", "keywords": ["gRPC"]}]

    assert add_skills({"skills": [{"name": "Tools", "keywords": ["docker"]}]},
                      [("Docker", "Tools")])["skills"][0]["keywords"] == ["docker"]

    asked = _ask({"ats_feedback": {"missing_keywords": OFFERED}})
    q = asked["current_question"]
    assert q["section"] == GATE_SECTION and q["offered"] == OFFERED
    assert q["options"] == [UPDATE_CHIP, KEEP_CHIP] and q["step"] == "confirm_update"
    accepted = skill_gap({"current_question": q, "latest_answer": UPDATE_CHIP})
    assert accepted["current_question"]["step"] == "claim_skills"
    declined = skill_gap({"current_question": q, "latest_answer": KEEP_CHIP})
    assert declined["skill_gap_asked"] is True and declined["current_question"] is None
    assert "Kubernetes, Terraform and gRPC" in q["question_text"]

    long_q = _ask({"ats_feedback": {"missing_keywords": [f"skill{i}" for i in range(20)]}})
    assert len(long_q["current_question"]["offered"]) == MAX_OFFERED

    assert _ask({}) == {"skill_gap_asked": True, "current_question": None}
    assert _ask({"ats_feedback": {"missing_keywords": []}})["current_question"] is None

    assert skill_gap({"current_question": accepted["current_question"], "latest_answer": NONE_CHIP}) ==\
        {"latest_answer": None, "current_question": None}

    print("skill_gap ok")
