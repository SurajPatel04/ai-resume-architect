"""Content the user hands over unprompted, filed into the section it belongs to."""

import logging
import re
from typing import Any, Dict, List, Optional

from app.graphs.node.confirm_import import ADDABLE, SECTION_WORDS, read_section
from app.graphs.state import ResumeState

logger = logging.getLogger(__name__)

SECTION_FIELDS = {section: fields for section, fields in ADDABLE.values()}

SECTION_LABELS = {section: label for label, (section, _) in ADDABLE.items()}

LIST_SECTIONS = ("experience", "education", "projects")

ADD_SECTION = "add_content"

AGAIN_CHIP = "Add it anyway"
SKIP_CHIP = "Skip — it's already there"

# How much of a pasted entry has to already be on the resume before it counts as the
# same one. Half, because people paste a project they have since added a bullet to.
BULLET_OVERLAP = 0.5

_NOISE = re.compile(r"[^a-z0-9]+")

def norm(text: Any) -> str:
    """Casefolded, punctuation-free text, for comparing what people wrote twice."""
    return _NOISE.sub(" ", str(text or "").casefold()).strip()

def entry_label(section: str, entry: Dict[str, Any]) -> str:
    """How to name an existing entry back to the user."""
    if section in ("projects", "certifications"):
        return entry.get("name") or "an untitled entry"
    if section == "experience":
        role, company = entry.get("position"), entry.get("company")
        return " at ".join(x for x in (role, company) if x) or "an untitled role"
    if section == "education":
        return entry.get("institution") or entry.get("study_type") or "an untitled qualification"
    return entry.get("name") or "that group"

def identifiers(section: str, entry: Dict[str, Any]) -> List[str]:
    """The strings that, if they appear in a paste, mean it is about this entry."""
    if section == "experience":
        names = (entry.get("company"), entry.get("position"))
    elif section == "education":
        names = (entry.get("institution"),)
    else:
        names = (entry.get("name"),)
    return [n for n in names if n and len(norm(n)) >= 4]

def bullets_of(entry: Dict[str, Any]) -> List[str]:
    if isinstance(entry.get("keywords"), list):
        return [str(k) for k in entry["keywords"]]
    return [str(b) for b in (entry.get("highlights") or [])]

def already_there(section: str, resume: Dict[str, Any], answer: str) -> Optional[Dict[str, Any]]:
    """The existing entry this paste duplicates, or None.

    Two signals, either sufficient. A name they wrote again is the obvious one. Bullet
    overlap catches the case the name misses: the same project pasted under a different
    heading, or a job re-sent with the title spelled differently, where the lines
    underneath are word for word what is already recorded.

    Deterministic on purpose. Asking a model "is this the same project?" costs a call
    to answer a question about text this already has both halves of.
    """
    pasted = norm(answer)
    lines = [norm(line) for line in (answer or "").splitlines()]
    lines = [line for line in lines if len(line) >= 12]

    for index, entry in enumerate(resume.get(section) or []):
        if not isinstance(entry, dict):
            continue

        for name in identifiers(section, entry):
            if norm(name) in pasted:
                return {"index": index, "label": entry_label(section, entry), "why": "name"}

        existing = [norm(b) for b in bullets_of(entry)]
        existing = [b for b in existing if len(b) >= 12]
        if not existing or not lines:
            continue

        shared = sum(1 for line in lines if line in existing)
        if shared / len(lines) >= BULLET_OVERLAP:
            return {"index": index, "label": entry_label(section, entry), "why": "bullets"}

    return None

# Everywhere a pasted entry might already be sitting. Searched in full rather than only
# in the section it is headed for: a project pasted as a job is the same project, and
# adding it silently is how the same work ends up on a resume twice under two headings.
SEARCH_SECTIONS = ("experience", "projects", "education", "certifications", "skills")

def find_anywhere(resume: Dict[str, Any], content: str) -> Optional[Dict[str, Any]]:
    """Where this content already sits, whichever section that turns out to be."""
    for section in SEARCH_SECTIONS:
        found = already_there(section, resume, content)
        if found:
            return {**found, "section": section}
    return None

def duplicate_question(section: str, found: Dict[str, Any], content: str) -> Dict[str, Any]:
    """Tell them where it already is, and let them decide."""
    here = SECTION_LABELS.get(found.get("section", section), section.title())
    going = SECTION_LABELS.get(section, section.title())
    seen = ("that entry is already recorded" if found["why"] == "name"
            else "those bullet points are already on it")

    if found.get("section") and found["section"] != section:
        text = (f"You already have **{found['label']}** under {here} — {seen}. "
                f"This would add it to {going} as well. Add it there too, or leave it?")
    else:
        text = (f"You already have **{found['label']}** under {here} — {seen}. "
                "Add it again as a separate entry, or leave it as it is?")

    return {
        # "system" so the chips cannot be captured as an answer to something else.
        "field": "system",
        "section": ADD_SECTION,
        "question_text": text,
        "ui": "chips",
        "options": [AGAIN_CHIP, SKIP_CHIP],
        "is_gate": False,
        "missing_fields": [],
        "bullet_index": None,
        # The paste rides on the question: answering "add it anyway" has to file the
        # content, and by then latest_answer is the chip they tapped.
        "meta": {"content": content, "add_section": section},
    }

# Shapes rather than words, for content whose wording names no section. A repository
# link is the strongest tell a resume has that something is a project; a date range or
# "at <Company>" is what a job looks like written down.
SHAPE_HINTS = (
    ("projects", re.compile(r"github\.com|gitlab\.com|\bhttps?://|\.dev\b|\.app\b", re.I), 8),
    ("experience", re.compile(r"\b(present|current)\b|\b(19|20)\d{2}\s*[-–—to]+\s*((19|20)\d{2}|present)", re.I), 7),
    ("experience", re.compile(r"\b(intern|engineer|developer|manager|analyst|consultant)\s+at\b", re.I), 9),
    ("certifications", re.compile(r"\b(certified|certificate|credential)\b", re.I), 8),
    ("education", re.compile(r"\b(b\.?tech|m\.?tech|bsc|msc|mca|bca|bachelor|master|degree|cgpa|gpa)\b", re.I), 8),
)

def section_scores(content: str) -> Dict[str, int]:
    """How strongly the content points at each section. Longer word, stronger signal."""
    reply = (content or "").casefold()
    scores: Dict[str, int] = {}

    for section, words in SECTION_WORDS.items():
        best = max((len(word) for word in words if word in reply), default=0)
        if best:
            scores[section] = max(scores.get(section, 0), best)

    for section, pattern, weight in SHAPE_HINTS:
        if pattern.search(content or ""):
            scores[section] = max(scores.get(section, 0), weight)

    return {s: score for s, score in scores.items() if s in SECTION_FIELDS}

def suggest_sections(content: str) -> List[str]:
    """Section labels, most likely first, every one still offered."""
    scores = section_scores(content)
    ranked = sorted(SECTION_FIELDS, key=lambda s: (-scores.get(s, 0), list(SECTION_FIELDS).index(s)))
    return [SECTION_LABELS[s] for s in ranked]

def section_question(content: str) -> Dict[str, Any]:
    """Ask where it goes, rather than guess or drop it.

    Reached when neither the classifier nor the wording names a section outright. The
    chips are ordered by what the content looks like, so the likely answer is the first
    thing under the thumb — but every section stays on offer, because the ranking is a
    guess about shape and the user is the one who knows.

    The paste rides along in `meta` for the same reason it does on the duplicate
    question: by the time they tap a chip, latest_answer is the chip.
    """
    ranked = suggest_sections(content)
    scores = section_scores(content)

    text = "Which section should that go in?"
    if scores:
        text = f"That looks like it belongs under **{ranked[0]}** — is that right?"

    return {
        "field": "system",
        "section": ADD_SECTION,
        "question_text": text,
        "ui": "chips",
        "options": ranked,
        "is_gate": False,
        "missing_fields": [],
        "bullet_index": None,
        "meta": {"content": content},
    }

def place(section: str, resume: Dict[str, Any], content: str,
          check_duplicate: bool = True) -> Dict[str, Any]:
    """File the content, or ask first if the resume already holds it.

    `check_duplicate` is off on the way back from "add it anyway" — they have already
    been told, and asking the same question about the same paste would never end.
    """
    if check_duplicate:
        found = find_anywhere(resume, content)
        if found:
            logger.info("Already recorded as %r under %s.", found["label"], found["section"])
            return {"current_question": duplicate_question(section, found, content)}

    logger.info("Filing volunteered content into %s.", section)
    return {"latest_answer": content, "current_question": content_question(section, resume)}

def target_section(state: ResumeState, answer: str) -> Optional[str]:
    """Which section the pasted entry belongs in, or None to go and ask.

    The planner names it as part of the classification that got us here, so this is
    normally free. Failing that, the content has to point somewhere clearly on its own:
    one section scoring above every other. A tie, or nothing at all, is a question —
    filing a coin-flip silently is how a project ends up under Work experience.

    Scored rather than keyword-matched, because the words overlap. `read_section` reads
    "github" as contact details, which is right when someone says "my github is wrong"
    and wrong for a repository link sitting inside a pasted project.
    """
    named = (state.get("add_section") or "").strip().casefold()
    if named in SECTION_FIELDS:
        return named

    scores = section_scores(answer)
    if not scores:
        return None

    ranked = sorted(scores, key=lambda section: -scores[section])
    if len(ranked) > 1 and scores[ranked[0]] == scores[ranked[1]]:
        return None

    return ranked[0]

def content_question(section: str, resume: Dict[str, Any]) -> Dict[str, Any]:
    """The question this content is the answer to, invented after the fact.

    extract_entities works off `current_question` — the section tells it which schema to
    parse into and the field tells merge_profile where to put the result. Nothing asked
    this, so it is built here and the user's message is handed straight to the extractor
    without a turn spent asking for what they have already given.
    """
    field = section
    if section in LIST_SECTIONS:
        field = f"{section}[{len(resume.get(section) or [])}]"

    return {
        "field": field,
        "section": section,
        # Empty on purpose: chat.py sends any question carrying text as a chat message,
        # and this one exists only to tell extract_entities which schema to use. The
        # user already knows what they pasted.
        "question_text": "",
        "ui": "text",
        "options": [],
        "is_gate": False,
        "missing_fields": list(SECTION_FIELDS[section]),
        "bullet_index": None,
        # The queue never asked for this, so merge_profile must not pop a gap for it.
        "standalone": True,
    }

def wants_it_anyway(answer: str) -> bool:
    """Did they choose to add a duplicate as its own entry? Unclear means no."""
    reply = norm(answer)
    if reply == norm(SKIP_CHIP) or reply.startswith("skip"):
        return False
    return reply == norm(AGAIN_CHIP) or "anyway" in reply or "again" in reply

def add_content(state: ResumeState) -> Dict[str, Any]:
    """File a volunteered entry, asking where it goes or whether it is already there."""
    answer = state.get("latest_answer") or ""
    resume = state.get("master_profile") or {}
    if hasattr(resume, "model_dump"):
        resume = resume.model_dump()

    pending = state.get("current_question") or {}
    stashed = (pending.get("meta") or {}) if pending.get("section") == ADD_SECTION else {}
    dismissed: Dict[str, Any] = {"latest_answer": None, "current_question": None}

    if stashed:
        content = stashed.get("content") or ""
        section = stashed.get("add_section")

        if section:
            if not wants_it_anyway(answer):
                logger.info("Duplicate declined; leaving the resume as it is.")
                return dismissed
            return place(section, resume, content, check_duplicate=False) if content else dismissed

        # They were picking a section for it.
        picked = read_section(answer)
        if not picked or not content:
            logger.info("Still no section for the pasted content; leaving it alone.")
            return dismissed
        return place(picked, resume, content)

    section = target_section(state, answer)
    if not section:
        logger.info("Could not place the volunteered content; asking which section.")
        return {"current_question": section_question(answer)}

    return place(section, resume, answer)
