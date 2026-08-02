"""The two answers that shape the interview instead of filling in the resume."""

import logging
from typing import Any, Dict, Optional

from app.graphs.apply import apply_extraction
from app.graphs.state import Resume, ResumeState

logger = logging.getLogger(__name__)

HAS_EXPERIENCE = ("internship", "experienced")

CAREER_SECTION = "career_level"
ROLE_SECTION = "target_role"

CAREER_CHIPS = {
    "Student / Fresher": "fresher",
    "Did an internship": "internship",
    "Working full-time": "experienced",
}

ROLE_CHIPS = (
    "Full Stack Developer",
    "Backend Engineer",
    "Frontend Engineer",
    "AI / ML Engineer",
    "Data Analyst",
    "DevOps Engineer",
    "Mobile Developer",
)

DECLINED = {"skip", "skip this", "not sure", "no idea", "dunno", "don't know",
            "dont know", "none", "no", "n/a"}

LEVEL_HINTS = (
    ("internship", ("intern",)),
    ("fresher", ("fresher", "student", "graduat", "college", "no experience", "final year")),
    ("experienced", ("working", "work at", "experien", "years", "full time", "full-time", "employed")),
)

def read_career_level(answer: str) -> Optional[str]:
    """Which of the three paths the user just put themselves on, or None if unclear."""
    reply = " ".join((answer or "").split()).lower()
    if not reply:
        return None

    for label, level in CAREER_CHIPS.items():
        if reply == label.lower():
            return level

    for level, hints in LEVEL_HINTS:
        if any(hint in reply for hint in hints):
            return level

    return None

def read_target_role(answer: str) -> Optional[str]:
    """The role as the user wrote it, or None if they named none."""
    role = " ".join((answer or "").split())
    if not role or len(role) > 80 or role.lower() in DECLINED:
        return None
    return role

def career_setup(state: ResumeState) -> Dict[str, Any]:
    """Record the career level or the target role, then let the queue be rebuilt."""
    pending = state.get("current_question") or {}
    answer = state.get("latest_answer") or ""

    if not answer.strip():

        return {}

    skipped = list(state.get("skipped") or [])

    done: Dict[str, Any] = {
        "latest_answer": None,
        "current_question": None,
        "question_queue": [],
    }

    if pending.get("section") == ROLE_SECTION:
        role = read_target_role(answer)
        if not role:
            logger.info("No target role in %r — dropping the question.", answer[:60])
            return {**done, "skipped": skipped + [ROLE_SECTION]}
        logger.info("Target role: %s", role)
        return {**done, "target_role": role}

    level = read_career_level(answer)
    if not level:

        logger.info("Could not classify %r — using the default section order.", answer[:60])
        return {**done, "skipped": skipped + [CAREER_SECTION]}

    logger.info("Career level: %s", level)
    done["career_level"] = level

    resume = state.get("master_profile") or {}
    if hasattr(resume, "model_dump"):
        resume = resume.model_dump()
    if level in HAS_EXPERIENCE and not (resume.get("experience") or []):
        logger.info("%s implies a role to describe — opening experience[0].", level)
        done["master_profile"] = Resume.model_validate(
            apply_extraction(resume, "experience[0]", {})
        ).model_dump()

    return done
