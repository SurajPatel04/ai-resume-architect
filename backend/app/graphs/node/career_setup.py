"""The two answers that shape the interview instead of filling in the resume.

Career level decides which sections get asked at all and in what order; the target role
decides what the skill chips offer. Neither is a field on the Resume, so neither can
travel the extract -> verify -> validate -> merge path every other answer takes. This
node writes them straight into state and clears the question queue, so analyze_gaps
replans against what it was just told.

Deterministic on purpose: the answer is a tap on a label this module also owns. Paying a
model to recognise its own chip buys nothing, and the free-text fallbacks below cover the
user who types instead.
"""

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
    """The role as the user wrote it, or None if they named none.

    Anything long is treated as "not a role name" rather than truncated — a sentence
    fragment driving the skill chips is worse than falling back to the plain question.
    """
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

if __name__ == "__main__":
                                                                                   
    for label, level in CAREER_CHIPS.items():
        assert read_career_level(label) == level, label

    assert read_career_level("i did a 6 month internship at zeta") == "internship"
    assert read_career_level("I'm a final year student with no experience") == "fresher"
    assert read_career_level("working full-time as an engineer for 3 years") == "experienced"
    assert read_career_level("3 years experience") == "experienced"
    assert read_career_level("") is None and read_career_level("hello there") is None

    assert read_career_level("intern with 1 year of experience") == "internship"

    assert read_target_role("Backend Engineer") == "Backend Engineer"
    assert read_target_role("  senior   sre  ") == "senior sre", "whitespace normalised"
    assert read_target_role("Prompt Engineer") == "Prompt Engineer", "a role nobody offered survives"
    assert read_target_role("skip") is None and read_target_role("not sure") is None
    assert read_target_role("") is None
    assert read_target_role("x" * 200) is None, "a paragraph is not a role name"

    def run(section, answer, skipped=None, profile=None):
        return career_setup({
            "current_question": {"field": section, "section": section},
            "latest_answer": answer,
            "question_queue": [{"field": section}, {"field": "skills"}],
            "skipped": skipped or [],
            "master_profile": profile if profile is not None else {},
        })

    level = run(CAREER_SECTION, "Student / Fresher")
    assert level["career_level"] == "fresher"
    assert level["question_queue"] == [], "the queue is stale once the path changes"
    assert level["current_question"] is None and level["latest_answer"] is None
    assert "skipped" not in level, "answering must not mark the question skipped"

    role = run(ROLE_SECTION, "Backend Engineer")
    assert role["target_role"] == "Backend Engineer" and "career_level" not in role

    for answer in ("Did an internship", "Working full-time"):
        opened = run(CAREER_SECTION, answer)
        assert opened["master_profile"]["experience"] == [{
            "company": "", "position": "", "location": "",
            "start_date": "", "end_date": "", "highlights": [],
        }], opened["master_profile"]["experience"]

    assert "master_profile" not in run(CAREER_SECTION, "Student / Fresher")

    filled = {"experience": [{"company": "Acme", "position": "Engineer"}]}
    assert "master_profile" not in run(CAREER_SECTION, "Working full-time", profile=filled)

    from app.graphs.node.analyze_gaps import infer_seniority
    assert infer_seniority(run(CAREER_SECTION, "Did an internship")["master_profile"]) == "unknown"

    assert run(CAREER_SECTION, "what do you mean")["skipped"] == [CAREER_SECTION]
    assert run(ROLE_SECTION, "not sure", skipped=["basics.phone"])["skipped"]\
        == ["basics.phone", ROLE_SECTION]

    assert run(CAREER_SECTION, "   ") == {}

    print("career_setup ok")
