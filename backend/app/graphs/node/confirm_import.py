"""Verify what came out of an uploaded document before treating it as fact.

The brief asks that an upload let the bot "start from a semi-completed state and only
ask verification questions". An LLM parse is a guess — merging it unchecked makes every
later question build on unverified data. This node shows the user what was picked up
and gives them one turn to correct it.

Two modes in one node (same shape as tailor_resume): ask, then process the reply.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.graphs.apply import apply_extraction
from app.graphs.state import Resume, ResumeState

logger = logging.getLogger(__name__)

CONFIRM_CHIP = "Yes, that's right"


class FieldCorrection(BaseModel):
    path: str = Field(
        description="Dotted path to the single field to fix, e.g. 'basics.name', "
        "'basics.email', 'experience[0].position', 'education[1].institution'. "
        "Indexes are 0-based and refer to the list shown in the profile."
    )
    value: str = Field(description="The corrected value, exactly as the user gave it.")


class ImportReview(BaseModel):
    confirmed: bool = Field(
        description="True if the user indicated the imported details are correct."
    )
    corrections: List[FieldCorrection] = Field(
        default_factory=list,
        description="Only fields the user explicitly asked to change. Empty if none. "
        "Never invent a correction the user did not state.",
    )


def _plural(items: list, word: str) -> str:
    return f"{len(items)} {word}{'' if len(items) == 1 else 's'}"


def summarise(r: Dict[str, Any]) -> str:
    """Plain-language account of what was parsed.

    Built from the data, not by an LLM — a summary of a parse must not itself be a guess.
    """
    parts = []
    experience = r.get("experience") or []
    if experience:
        top = experience[0]
        role = " at ".join(x for x in (top.get("position"), top.get("company")) if x)
        parts.append(_plural(experience, "role") + (f" (most recent: {role})" if role else ""))

    education = r.get("education") or []
    if education:
        parts.append(_plural(education, "qualification"))

    keywords = sum(len(c.get("keywords") or []) for c in (r.get("skills") or []))
    if keywords:
        parts.append(f"{keywords} skill{'' if keywords == 1 else 's'}")

    projects = r.get("projects") or []
    if projects:
        parts.append(_plural(projects, "project"))

    return ", ".join(parts)


def split_path(path: str) -> Tuple[Optional[str], Optional[str]]:
    """'experience[0].position' -> ('experience[0]', 'position'). None if unusable."""
    container, _, key = (path or "").strip().rpartition(".")
    if not container or not key or "[" in key:
        return None, None
    return container, key


def _is_empty(r: Dict[str, Any]) -> bool:
    """Nothing worth confirming — a failed parse, or a first message that wasn't a resume."""
    return not any((
        (r.get("basics") or {}).get("name"),
        r.get("experience"),
        r.get("education"),
        r.get("skills"),
        r.get("projects"),
    ))


def _ask(r: Dict[str, Any], retried: bool) -> Dict[str, Any]:
    if retried:
                                                                                      
                                   
        text = 'No problem — what should I change? For example: "the company is Globex, not Acme".'
        ui, options = "text", []
    else:
        summary = summarise(r)
        first_name = ((r.get("basics") or {}).get("name") or "").split(" ")[0]
        greeting = f"Thanks, {first_name}! " if first_name else "Thanks! "
        if summary:
            text = f"{greeting}I picked up {summary}. Does that look right?"
        else:
            text = f"{greeting}I read your document but couldn't pull much out of it. Want to tell me about your most recent role?"
        ui, options = "chips", [CONFIRM_CHIP]

    return {
        "current_question": {
            "field": "import",
            "section": "import",
            "question_text": text,
            "ui": ui,
            "options": options,
            "is_gate": False,
            "missing_fields": [],
            "bullet_index": None,
            "retried": retried,
        },
        "import_confirmed": False,
    }


def confirm_import(state: ResumeState) -> Dict[str, Any]:
    resume = state.get("master_profile") or {}
    r = resume.model_dump() if hasattr(resume, "model_dump") else resume

    pending = state.get("current_question") or {}
    answer = state.get("latest_answer")
    replying = bool(answer) and pending.get("section") == "import"

    if not replying:
                                                                                 
        if _is_empty(r):
            logger.info("Import produced nothing to confirm; skipping verification.")
            return {"import_confirmed": True}
        logger.info("Asking the user to verify the imported profile.")
        return _ask(r, retried=False)

                                              
    done = {"latest_answer": None, "current_question": None, "import_confirmed": True}

    if answer.strip() == CONFIRM_CHIP:
        logger.info("Import confirmed by chip.")
        return done

                                                                                     
                                                                              
    from app.utils.llm import get_openai_llm

    try:
        review: ImportReview = get_openai_llm().with_structured_output(
            ImportReview, method="function_calling"
        ).invoke(f"""
    A resume was parsed from the user's uploaded document. We showed them a summary and
    asked whether it looked right.

    PARSED PROFILE:
    {r}

    OUR QUESTION: {pending.get("question_text")}
    THEIR REPLY: "{answer}"

    Decide whether they confirmed it, and list ONLY the specific fields they asked to
    change. If they said something is wrong but didn't say what, return confirmed=false
    with no corrections. Never invent a correction they did not state.
    """)
    except Exception as e:
                                                                             
        logger.error(f"Import review failed: {e}")
        return done

    if review.corrections:
        candidate = r
        applied = []
        for correction in review.corrections:
            container, key = split_path(correction.path)
            if not container:
                logger.warning("Ignoring unusable correction path: %r", correction.path)
                continue
                                                                      
            candidate = apply_extraction(candidate, container, {key: correction.value}, replace=True)
            applied.append(correction.path)

        try:
            validated = Resume.model_validate(candidate)
        except Exception as e:
            logger.warning(f"Corrections failed validation, keeping the original import: {e}")
            return done

        logger.info("Applied import corrections: %s", ", ".join(applied) or "none")
        return {**done, "master_profile": validated.model_dump()}

    if not review.confirmed and not pending.get("retried"):
                                                                    
        logger.info("Import rejected without specifics; asking once for detail.")
        return {**_ask(r, retried=True), "latest_answer": None}

    return done


if __name__ == "__main__":
    profile = {
        "basics": {"name": "Priya Sharma", "email": "p@x.com"},
        "experience": [
            {"company": "Acme", "position": "Marketing Lead"},
            {"company": "Globex", "position": "Analyst"},
        ],
        "education": [{"institution": "IIT Bombay"}],
        "skills": [{"name": "Core", "keywords": ["SEO", "Python", "Figma"]}],
        "projects": [],
    }

    assert summarise(profile) == "2 roles (most recent: Marketing Lead at Acme), 1 qualification, 3 skills", summarise(profile)
    assert summarise({"experience": [{"company": "Acme", "position": "Lead"}]}) == "1 role (most recent: Lead at Acme)"
                                                                          
    assert summarise({"experience": [{"company": "Acme"}]}) == "1 role (most recent: Acme)"
    assert summarise({"experience": [{"position": "Lead"}]}) == "1 role (most recent: Lead)"
    assert summarise({"experience": [{}]}) == "1 role", "nothing to name, no parenthetical"
    assert summarise({}) == ""

    assert split_path("experience[0].position") == ("experience[0]", "position")
    assert split_path("basics.name") == ("basics", "name")
    assert split_path("basics") == (None, None), "a bare section names no field"
    assert split_path("") == (None, None)
    assert split_path("experience.[0]") == (None, None), "index must not be the leaf"

    assert _is_empty({}) and _is_empty({"basics": {"name": ""}, "experience": []})
    assert not _is_empty(profile)

                                              
    asked = confirm_import({"master_profile": profile})
    assert asked["import_confirmed"] is False
    assert asked["current_question"]["section"] == "import"
    assert CONFIRM_CHIP in asked["current_question"]["options"]
    assert "Priya" in asked["current_question"]["question_text"]
    assert len(asked["current_question"]["question_text"].split()) < 60, "mobile-first: keep it short"

    assert confirm_import({"master_profile": {}}) == {"import_confirmed": True}

                                               
    retry = _ask(profile, retried=True)
    assert retry["current_question"]["question_text"] != asked["current_question"]["question_text"]
    assert retry["current_question"]["ui"] == "text", "asking what to fix needs free text"
    assert retry["current_question"]["retried"] is True

                                                               
    tapped = confirm_import({
        "master_profile": profile,
        "latest_answer": CONFIRM_CHIP,
        "current_question": {"section": "import"},
    })
    assert tapped == {"latest_answer": None, "current_question": None, "import_confirmed": True}

    print("confirm_import ok")
