"""Whose layout the finished PDF should wear."""

import logging
import re
from typing import Any, Dict, Optional

from app.graphs.node.render_resume import SECTION_KEYS, Style, clean_style
from app.graphs.state import ResumeState
from app.graphs.prompts import READ_LAYOUT
from app.utils.pdf_style import measured_style
from app.utils.vision import image_message, page_as_png

logger = logging.getLogger(__name__)

STYLE_SECTION = "choose_style"

MINE_CHIP = "Match my original layout"
SITE_CHIP = "Use this site's layout"

def style_question() -> Dict[str, Any]:
    return {
        # "system" so the answer cannot be captured as an answer to something else.
        "field": "system",
        "section": STYLE_SECTION,
        "question_text": (
            "One last thing before I build the PDF — should it look like the resume you "
            "uploaded, or like this site's template? Matching yours copies the type, the "
            "headings and the section order; the wording stays as we've written it."
        ),
        "ui": "chips",
        "options": [MINE_CHIP, SITE_CHIP],
        "is_gate": False,
        "missing_fields": [],
        "bullet_index": None,
    }

def described(measured: Dict[str, Any]) -> str:
    """The measurements, written out for the model to read."""
    if not measured:
        return ("- nothing. This file gave up no measurements at all — it is scanned, "
                "flattened or drawn as one image. Everything below is yours to answer.")
    return "\n".join(f"- {field}: {value!r}" for field, value in sorted(measured.items()))

def read_style(pdf_path: str) -> Optional[Style]:
    """The uploaded resume's layout: measured where it can be, described where it cannot.

    Colour, geometry, type and placement are measured. The model is reading a picture:
    it answers a shade or two out on colour, can only estimate how wide the dark band
    is, and cannot name a typeface from its shapes at all. The PDF states every one of
    those outright, so the file wins wherever the two disagree.

    The model is not therefore useless — it is shown the measurements and asked for what
    is missing from them. On a scanned or flattened resume nothing is measurable and its
    answer is the whole of the layout; on a clean export it fills the few judgements a
    file does not record. Two sources, each doing what it is actually good at.
    """
    measured = measured_style(pdf_path)

    png = page_as_png(pdf_path)
    if not png:
        logger.warning("No image to read a layout from; going on the measurements alone.")
        return clean_style(Style(**{k: v for k, v in measured.items()
                                    if k in Style.model_fields})) if measured else None

    from app.utils.llm import get_openai_vision_llm

    try:
        spec: Style = get_openai_vision_llm().with_structured_output(
            Style, method="function_calling"
        ).invoke(image_message(png, READ_LAYOUT.format(
            sections=", ".join(SECTION_KEYS), measured=described(measured))))
    except Exception as e:
        logger.error("Could not read the layout off %s: %r", pdf_path, e)
        spec = Style()

    cleaned = clean_style(spec)

    if cleaned:
        for field, value in measured.items():
            if hasattr(cleaned, field):
                setattr(cleaned, field, value)
        cleaned = clean_style(cleaned)

    if cleaned:
        logger.info("Read their layout: %d fields measured, the rest described. "
                    "%s %s, name %s, headings %s%s, order %s",
                    len(measured), cleaned.body_font or cleaned.font_family,
                    f"{cleaned.body_size_pt}pt" if cleaned.body_size_pt else "",
                    cleaned.name_align, cleaned.heading_case,
                    " with a rule" if cleaned.heading_rule else "",
                    ", ".join(cleaned.section_order))
    return cleaned

# A reply must be about layout AND possessive: bare "my" matched edit requests.
LAYOUT_WORDS = ("layout", "format", "style", "design", "template", "original", "uploaded", "look")

MINE_WORDS = ("my", "mine", "our", "original", "uploaded", "same")

SITE_WORDS = ("site", "your", "yours", "default", "standard", "template", "yours")

def wants_own_style(answer: str) -> bool:
    """Did they ask for their own layout? Anything unclear keeps the site's."""
    reply = (answer or "").strip().casefold()
    if reply == SITE_CHIP.casefold():
        return False
    if reply == MINE_CHIP.casefold():
        return True

    words = set(re.findall(r"[a-z]+", reply))
    if not words & set(LAYOUT_WORDS):
        return False
    if "site" in words or "yours" in words or "your" in words:
        return False
    return bool(words & set(MINE_WORDS))

def wants_site_style(answer: str) -> bool:
    """Did they ask for this site's layout outright?

    Worth its own question rather than "not wants_own_style", which is also true of
    "hello". Someone who has already said which one they want must not be shown the two
    chips again — being asked a question you have just answered reads as not being
    listened to, and there is nothing to do but answer it a second time.
    """
    reply = (answer or "").strip().casefold()
    if reply == MINE_CHIP.casefold():
        return False
    if reply == SITE_CHIP.casefold():
        return True

    words = set(re.findall(r"[a-z]+", reply))
    if not words & set(LAYOUT_WORDS):
        return False
    if words & {"my", "mine", "our", "original", "uploaded"}:
        return False
    return bool(words & set(SITE_WORDS))

def cannot_match(reason: str) -> Dict[str, Any]:
    """They asked for their own layout and it could not be read. Say so.

    Falling back quietly is right when nobody asked — the PDF still gets built. It is
    wrong when the request WAS to match their original: the same site template comes
    back with the same chip under it, and the only thing they learn is that asking did
    nothing.
    """
    return {
        "latest_answer": None,
        "style_choice": "site",
        "current_question": {
            # "system" so this confirmation cannot capture the next answer.
            "field": "system",
            "question_text": reason,
            "ui": "text",
            "options": [],
        },
    }

NO_ORIGINAL = (
    "I don't have an original to copy — this resume was built from scratch rather than "
    "uploaded. Upload the PDF you'd like me to match and ask again."
)

UNREADABLE = (
    "I couldn't read the layout off your uploaded resume, so the PDF is in this site's "
    "template. Upload it again and ask, and I'll have another go."
)

def choose_style(state: ResumeState) -> Dict[str, Any]:
    """Ask whose layout to use, then read it if they said theirs.

    The choice is not final. RESTYLE means they have come back to change it, whatever
    they picked the first time — it used to be recorded once and then treated as settled
    forever, so "actually, use my original" was read as an edit to the resume and
    answered with a request to clarify what they meant.
    """
    answer = state.get("latest_answer") or ""
    restyling = state.get("workflow_type") == "RESTYLE"

    if state.get("style_choice") and not restyling:
        return {}

    source = state.get("source_pdf")
    pending = state.get("current_question") or {}
    answering = bool(answer) and pending.get("section") == STYLE_SECTION

    if not source:
        if restyling and wants_own_style(answer):
            logger.info("Asked for their own layout with nothing uploaded to match.")
            return cannot_match(NO_ORIGINAL)
        logger.info("No uploaded resume to match; using the site template.")
        return {"style_choice": "site"}

    # A restyle that already says which way it wants needs no question — either way
    # round. One that does not — "change the layout" — gets the same two chips as the
    # first time.
    decided = restyling and (wants_own_style(answer) or wants_site_style(answer))
    if not answering and not decided:
        logger.info("Asking whose layout the PDF should use.")
        return {"current_question": style_question()}

    done: Dict[str, Any] = {"latest_answer": None, "current_question": None}

    if not wants_own_style(answer):
        logger.info("Using the site template.")
        return {**done, "style_choice": "site", "style_spec": None}

    style = read_style(source)
    if not style:
        if restyling:
            return cannot_match(UNREADABLE)
        # Nobody asked for this specifically — build in the site template and move on.
        return {**done, "style_choice": "site", "style_spec": None}

    return {**done, "style_choice": "mine", "style_spec": style.model_dump()}
