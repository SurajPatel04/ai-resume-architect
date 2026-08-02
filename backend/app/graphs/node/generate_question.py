import json
import logging
from typing import Any, Dict
from app.graphs.state import ResumeState
from app.graphs.node.career_setup import CAREER_CHIPS, ROLE_CHIPS
from app.graphs.prompts import (
    GENERATE_QUESTION, QUESTION_ERROR_CONTEXT, QUESTION_INSTRUCTIONS,
    SKILL_CHIPS, SKILL_CHIPS_COLD, SKILL_CHIPS_EVIDENCE,
)
from app.utils.llm import get_openai_llm
from pydantic import BaseModel, Field
from typing import List, Literal

logger = logging.getLogger(__name__)

IMPACT_OPTIONS = ["I don't have a number", "Skip this one"]

YES_CHIP = "Yes"
NO_CHIP = "No, skip this"

SKIP_CHIP = "Skip this"

DATE_FIELDS = ("start_date", "end_date")

GATE_PROMPTS = {
    "experience": ("Do you have any work experience to add?", [YES_CHIP, NO_CHIP]),
    "education": ("Do you have any education to add?", [YES_CHIP, NO_CHIP]),
    "projects": ("Any projects worth listing?", [YES_CHIP, NO_CHIP]),

    "skills": (
        "What are your main skills? Group them by category, for example: "
        "`Languages: Python, TypeScript` and `Frontend: React, CSS`.",
        ["Skip this"],
    ),

    "career_level": ("Where are you right now in your career?", list(CAREER_CHIPS)),
    "target_role": (
        "Which role are you targeting? Tap one, or type it if it's not here — "
        "your answer decides which skills I suggest next.",
        list(ROLE_CHIPS),
    ),
}

MORE_PROMPTS = {
    "experience": ("Any other work experience to add?", [YES_CHIP, NO_CHIP]),
    "education": ("Any other degrees or qualifications to add?", [YES_CHIP, NO_CHIP]),
    "projects": ("Any other projects to add?", [YES_CHIP, NO_CHIP]),
}

class SuggestedSkills(BaseModel):
    skills: List[str] = Field(
        default_factory=list,
        description="8-12 concrete languages, frameworks and tools that job postings for this "
        "role actually name. No soft skills, no sentences, no duplicates.",
    )

def used_technologies(resume: Dict[str, Any]) -> str:
    """Everything the candidate has already described doing, in their own words."""
    lines: List[str] = []
    for job in resume.get("experience") or []:
        lines.extend(job.get("highlights") or [])
    for project in resume.get("projects") or []:
        if project.get("description"):
            lines.append(project["description"])
        lines.extend(project.get("highlights") or [])

    return "\n".join(f"- {line}" for line in lines[:20] if str(line).strip())

def role_skill_chips(role: str, evidence: str = "") -> List[str]:
    """Skills to tap for `role`, instead of a blank box to type into."""
    already = (
        SKILL_CHIPS_EVIDENCE.format(evidence=evidence, role=role)
        if evidence.strip() else SKILL_CHIPS_COLD
    )
    prompt = SKILL_CHIPS.format(role=role, evidence=already)

    try:
        result: SuggestedSkills = get_openai_llm().with_structured_output(
            SuggestedSkills, method="function_calling"
        ).invoke(prompt)
    except Exception as e:
        logger.error("Could not suggest skills for %r: %r", role, e)
        return []

    seen, chips = set(), []
    for skill in result.skills:
        name = (skill or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            chips.append(name)
    return chips[:12]

def known_context(state: ResumeState, field: str) -> str:
    """What the interview already knows, put in front of the question it asks next."""
    lines = []

    if state.get("career_level"):
        lines.append(f"- They described themselves as: {state['career_level']}")
    if state.get("target_role"):
        lines.append(f"- Role they are targeting: {state['target_role']}")

    resume = state.get("master_profile") or {}
    if hasattr(resume, "model_dump"):
        resume = resume.model_dump()

    filled = [s for s in ("experience", "education", "projects", "skills", "certifications")
              if resume.get(s)]
    if filled:
        lines.append(f"- Sections already recorded: {', '.join(filled)}")

    recorded = {k: v for k, v in (current_item(resume, field) or {}).items() if v}
    if recorded:
        lines.append(f"- Already recorded for {field}: {json.dumps(recorded, ensure_ascii=False)}")

    if not lines:
        return ""
    return "WHAT YOU ALREADY KNOW ABOUT THIS CANDIDATE:\n" + "\n".join(lines)

def current_item(resume: Dict[str, Any], field: str) -> Dict[str, Any]:
    """The entry a question is about: 'experience[0]' -> that job, 'basics' -> basics."""
    name, _, index = (field or "").partition("[")
    value = resume.get(name)
    if index:
        if not isinstance(value, list):
            return {}
        i = int(index.rstrip("]") or 0)
        value = value[i] if i < len(value) else {}
    return value if isinstance(value, dict) else {}

def says_yes(answer: str) -> bool:
    """A tap on an affirmative chip, or the typed equivalent."""
    reply = (answer or "").strip().lower().lstrip("*_ ")
    return reply.startswith(("yes", "yeah", "yep", "sure", "ok", "let's", "lets"))

AFFIRMATIONS = frozenset({
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "y", "true", "correct",
    "yes please", "of course", "i do", "let's go", "lets go", "definitely",
})

def is_affirmation(value: Any) -> bool:
    """Is this value just the word the user tapped to say a section exists?"""
    return str(value or "").strip().strip(".,!").lower() in AFFIRMATIONS

def with_skip(ui: str, options: List[str]) -> tuple:
    """Add the way out, promoting a bare text box to chips over a text box."""

    options = list(dict.fromkeys(str(option) for option in (options or []) if str(option).strip()))
    if SKIP_CHIP in options:
        return ui, options
    return ("chips" if ui == "text" else ui), options + [SKIP_CHIP]

class GeneratedQuestion(BaseModel):
    question_text: str = Field(description="The short, polite question to ask the user.")
    ui: Literal["text", "chips"] = Field(description="Use 'chips' if there are 2-5 distinct short options (e.g. Yes/No, or specific skills), otherwise use 'text'.")
    options: List[str] = Field(default_factory=list, description="A list of 2-5 short options if ui is 'chips'.")

def quote_bullet(bullet: Any, question: str) -> str:
    """Put what the resume already says in front of the question that's about it."""
    lines = bullet if isinstance(bullet, list) else [bullet]
    lines = [str(line).strip() for line in lines if str(line or "").strip()]
    if not lines:
        return question
    return "Your resume says:\n\n" + "\n>\n".join(f"> {line}" for line in lines) + f"\n\n{question}"

def entry_label(resume: Dict[str, Any], target_gap: Dict[str, Any]) -> str:
    """How to refer to the entry a question is about, in the user's own words."""
    item = current_item(resume, target_gap.get("field", ""))
    section = target_gap.get("section", "")

    if section == "education":
        study = item.get("study_type") or item.get("area")
        where = item.get("institution")
        return " at ".join(x for x in (f"studying {study}" if study else "", where) if x) or "there"

    role, company = item.get("position"), item.get("company")
    if role and company:
        return f"{role} at {company}"
    return role or (f"at {company}" if company else "there")

def recorded_values(resume: Dict[str, Any], field: str, fields: List[str]) -> List[str]:
    """What the resume currently holds for the fields a follow-up is about."""
    item = current_item(resume, field)
    out: List[str] = []
    for name in fields or []:
        value = item.get(name)
        for line in (value if isinstance(value, list) else [value]):
            if str(line or "").strip():
                out.append(str(line).strip())
    return out

def impact_question(target_gap: Dict[str, Any]) -> str:
    """A deterministic, self-contained question about one exact resume bullet."""
    bullet = target_gap.get("weak_bullet", "")
    reason = str(target_gap.get("reason") or "it does not yet show a clear result").rstrip(".")
    entry = target_gap.get("entry")

    asked = (
        f"Why it could be stronger: {reason}. What changed after your work? "
        "Share any real result you remember — for example time saved, cost, reliability, "
        "speed, users, conversion, or error reduction."
    )
    quoted = quote_bullet(bullet, asked)
    return f"**{entry}**\n\n{quoted}" if entry else quoted

def generate_question(state: ResumeState) -> Dict[str, Any]:
    """Uses the LLM to generate the natural language question based on active_target. Returns
    the result in state.current_question.
    """
    target_gap = state.get("active_target")
    if not target_gap:
        return {"current_question": None}

    if target_gap.get("question_text"):
        resume = state.get("master_profile") or {}
        if hasattr(resume, "model_dump"):
            resume = resume.model_dump()
        return {
            "current_question": {
                "field": target_gap["field"],
                "question_text": quote_bullet(
                    recorded_values(resume, target_gap["field"], target_gap.get("missing_fields", [])),
                    target_gap["question_text"],
                ),
                "section": target_gap.get("section", ""),

                "ui": "chips",
                "options": [SKIP_CHIP],
                "is_gate": False,
                "missing_fields": target_gap.get("missing_fields", []),
                "bullet_index": None,

                "is_follow_up": True,
            },
        }

    llm = get_openai_llm()

    errors = state.get("validation_errors", [])
    error_context = QUESTION_ERROR_CONTEXT.format(error=errors[-1]) if errors else ""

    missing_fields = target_gap.get("missing_fields", [])
    is_gate = target_gap.get("is_gate", False)

    missing_str = ", ".join(missing_fields) if missing_fields else "the information"

    prompts = MORE_PROMPTS if target_gap.get("is_more") else GATE_PROMPTS
    gate_prompt = prompts.get(target_gap.get("section")) if is_gate else None
    if gate_prompt:
        text, options = gate_prompt
        ui = "chips"

        role = state.get("target_role")
        if target_gap.get("section") == "skills" and role:
            profile = state.get("master_profile") or {}
            if hasattr(profile, "model_dump"):
                profile = profile.model_dump()

            suggested = role_skill_chips(role, used_technologies(profile))
            if suggested:
                text = (
                    f"These are the skills {role} postings ask for most. Tap the ones you "
                    "actually use, then send — and type any I've missed. You can group your "
                    "skills as `Languages: Python, TypeScript` and `Frontend: React, CSS`."
                )
                ui, options = "multi_select", suggested

        return {
            "current_question": {
                "field": target_gap["field"],
                "question_text": text,
                "section": target_gap.get("section", ""),
                "ui": ui,
                "options": options,
                "is_gate": True,
                "missing_fields": missing_fields,
                "bullet_index": None,
            },
        }

    if target_gap.get("skip_section_if_empty"):

        return {
            "current_question": {
                "field": target_gap["field"],
                "question_text": (
                    "Tell me about a project you would like on your resume. Include its "
                    "name, what you built, and the strongest outcomes or features."
                ),
                "section": target_gap.get("section", ""),
                "ui": "chips",
                "options": [SKIP_CHIP],
                "is_gate": False,
                "skip_section_if_empty": True,
                "missing_fields": target_gap.get("missing_fields", []),
                "bullet_index": None,
            },
        }

    if missing_fields and set(missing_fields) <= set(DATE_FIELDS):
        resume = state.get("master_profile") or {}
        if hasattr(resume, "model_dump"):
            resume = resume.model_dump()
        return {
            "current_question": {
                "field": target_gap["field"],
                "question_text": f"When were you {entry_label(resume, target_gap)}?",
                "section": target_gap.get("section", ""),
                "ui": "dates",

                "options": [SKIP_CHIP],
                "is_gate": False,
                "missing_fields": missing_fields,
                "bullet_index": None,
            },
        }

    if target_gap.get("section") == "experience":
        resume = state.get("master_profile") or {}
        if hasattr(resume, "model_dump"):
            resume = resume.model_dump()
        existing = current_item(resume, target_gap["field"])
        company, position = existing.get("company"), existing.get("position")
        if company and position:
            return {
                "current_question": {
                    "field": target_gap["field"],
                    "question_text": (
                        f"For your {position} role at {company}, please share when you worked "
                        "there (start and end date, or Present) and 2–4 bullet points describing "
                        "what you built, improved, or achieved."
                    ),
                    "section": "experience",
                    "ui": "chips",
                    "options": [SKIP_CHIP],
                    "is_gate": False,
                    "missing_fields": target_gap.get("missing_fields", []),
                    "bullet_index": None,
                },
            }

    if target_gap.get("section") == "impact":
        rewrite = target_gap.get("rewrite") or ""

        return {
            "current_question": {
                "field": target_gap["field"],
                "question_text": impact_question(target_gap),
                "section": "impact",

                # No usable rewrite means the plain free-text question.
                "ui": "metric" if rewrite else "chips",
                "options": IMPACT_OPTIONS,
                "is_gate": False,
                "skip_section_if_empty": False,
                "missing_fields": target_gap.get("missing_fields", []),
                "bullet_index": target_gap.get("bullet_index"),

                "meta": {"template": rewrite} if rewrite else None,
            },
        }
    else:
        instructions = QUESTION_INSTRUCTIONS.format(
            field=target_gap["field"], missing=missing_str, reason=target_gap["reason"]
        )

    prompt = GENERATE_QUESTION.format(
        error_context=error_context,
        known_context=known_context(state, target_gap["field"]),
        instructions=instructions,
    )

    try:
        structured_llm = llm.with_structured_output(GeneratedQuestion)
        response: GeneratedQuestion = structured_llm.invoke(prompt)
        question_text = response.question_text
        ui = response.ui
        options = response.options
    except Exception as e:
        logger.error(f"Failed to generate question: {e}")
        question_text = f"Could you please provide information for {target_gap['field']}? ({target_gap['reason']})"
        ui = "text"
        options = []

    if target_gap.get("skip_section_if_empty"):

        ui, options = "chips", [SKIP_CHIP]
    else:

        ui, options = with_skip(ui, options)

    return {
        "current_question": {
            "field": target_gap["field"],
            "question_text": question_text,
            "section": target_gap.get("section", ""),
            "ui": ui,
            "options": options,
            "is_gate": is_gate,
            "skip_section_if_empty": target_gap.get("skip_section_if_empty", False),
            "missing_fields": missing_fields,

            "bullet_index": target_gap.get("bullet_index"),
        },

    }
