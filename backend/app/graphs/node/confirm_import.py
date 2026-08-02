"""Verify what came out of an uploaded document before treating it as fact."""

import logging
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.graphs.apply import apply_extraction
from app.graphs.state import Resume, ResumeState
from app.graphs.prompts import IMPORT_REVIEW
from app.utils.prompt import compact

logger = logging.getLogger(__name__)

CONFIRM_CHIP = "Yes, that's right"

FIX_CHIP = "Something's missing"

# Sections the user can point at, and the gap each one becomes.
ADDABLE = {
    "Work experience": ("experience", ["company", "position", "start_date", "end_date", "highlights"]),
    "Education": ("education", ["institution", "area", "study_type", "end_date"]),
    "Projects": ("projects", ["name", "description", "highlights"]),
    "Skills": ("skills", ["skills"]),
    "Certifications or awards": ("certifications", ["name", "issuer", "date"]),
    "Contact details": ("basics", ["name", "email", "phone", "location"]),
}

SECTION_CHIPS = list(ADDABLE)

# Only consulted at the picker step, where a bare "name" means contact details.
SECTION_WORDS = {
    "experience": ("experience", "work", "job", "role", "employ", "intern", "position", "company"),
    "education": ("education", "degree", "college", "university", "school", "qualification", "study",
                  "b.tech", "btech", "mca", "bsc", "msc"),
    "projects": ("project", "portfolio", "side project"),
    "skills": ("skill", "tech stack", "technolog", "tool", "language", "framework"),
    "certifications": ("cert", "award", "licen", "honour", "honor", "achievement", "badge"),
    "basics": ("contact", "email", "phone", "number", "linkedin", "github", "location", "address",
               "website", "portfolio link", "my name"),
}

def read_section(answer: str) -> Optional[str]:
    """Which section they named, tapped or typed, or None if it isn't one."""
    tapped = ADDABLE.get((answer or "").strip())
    if tapped:
        return tapped[0]

    reply = (answer or "").strip().casefold()
    if not reply:
        return None

    best: Optional[str] = None
    longest = 0
    for section, words in SECTION_WORDS.items():
        for word in words:
            if word in reply and len(word) > longest:
                best, longest = section, len(word)
    return best

def section_gap(section: str, r: Dict[str, Any]) -> Dict[str, Any]:
    """A question about `section`, in the shape analyze_gaps would have queued."""
    fields = next((f for label, (name, f) in ADDABLE.items() if name == section), ["name"])

    field = section
    if section in ("experience", "education", "projects"):
        field = f"{section}[{len(r.get(section) or [])}]"

    return {
        "field": field,
        "section": section,
        "kind": "required",
        "missing_fields": list(fields),
        "is_gate": False,
        "reason": f"They said their {section} was missing from the import.",
    }

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

def _headed(items: list, heading: str) -> str:
    """Count a section by the heading its own resume gives it.

    "Awards" is already a plural and reads as one — "3 awards". "Volunteering" is not,
    and "2 volunteerings" is not English, so those are counted in entries instead.
    """
    label = heading.strip().lower()
    if label.endswith("s"):
        return f"{len(items)} {label[:-1] if len(items) == 1 else label}"
    return f"{len(items)} {label} entr{'y' if len(items) == 1 else 'ies'}"

def summarise(r: Dict[str, Any]) -> str:
    """Plain-language account of what was parsed."""
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

    certifications = r.get("certifications") or []
    if certifications:
        parts.append(_plural(certifications, "certification"))

    # Whatever else their document carried. Counted by its own heading, because a
    # summary that stops at the four sections this schema happens to name reads as
    # having thrown the rest away — which is exactly what it used to do.
    for section in r.get("custom_sections") or []:
        if not isinstance(section, dict):
            continue
        entries = section.get("entries") or []
        name = str(section.get("name") or "").strip()
        if entries and name:
            parts.append(_headed(entries, name))

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
        r.get("certifications"),
        # Counted too: a document whose content is all Awards and Volunteering was read
        # perfectly well, and skipping verification would say it read nothing.
        any((s or {}).get("entries") for s in (r.get("custom_sections") or [])),
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
        ui, options = "chips", [CONFIRM_CHIP, FIX_CHIP]

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

def _pick() -> Dict[str, Any]:
    """The section picker, shown when they say something is missing."""
    return {
        "current_question": {
            "field": "import",
            "section": "import",
            "question_text": (
                "Which part is missing? Tap one and I'll ask about it — "
                "or just type what's wrong."
            ),
            "ui": "chips",
            "options": SECTION_CHIPS,
            "is_gate": False,
            "missing_fields": [],
            "bullet_index": None,
            "retried": False,

            "picking": True,
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

    if answer.strip() == FIX_CHIP:
        logger.info("Import flagged as incomplete; offering the sections.")
        return _pick()

    if pending.get("picking"):
        section = read_section(answer)
        if section:
            # import_confirmed so analyze_gaps runs; it keeps a non-empty queue.
            logger.info("They want to fill in %s; queueing a question about it.", section)
            return {**done, "question_queue": [section_gap(section, r)]}

        logger.info("Couldn't place %r as a section; reading it as a correction.", answer)

    from app.utils.llm import get_openai_llm

    try:
        review: ImportReview = get_openai_llm().with_structured_output(
            ImportReview, method="function_calling"
        ).invoke(IMPORT_REVIEW.format(
            resume=compact(r), question=pending.get("question_text"), answer=answer
        ))
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
