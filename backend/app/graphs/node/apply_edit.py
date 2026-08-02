"""Applies a change the user asked for out loud, to a field that is already filled."""

import logging
from typing import Any, Dict, List, Literal, Type, Union

from pydantic import BaseModel, Field, create_model

from app.graphs.apply import apply_extraction
from app.graphs.state import (
    Basics, Certification, Education, Experience, Project, Resume, ResumeState,
    SkillCategory, Summary,
)
from app.graphs.prompts import EDIT_PLAN
from app.utils.llm import get_openai_llm

logger = logging.getLogger(__name__)

# Containers a user can ask to change, and the model each one holds.
EDITABLE: Dict[str, Type[BaseModel]] = {
    "basics": Basics,
    "summary": Summary,
    "experience": Experience,
    "education": Education,
    "projects": Project,
    "skills": SkillCategory,
    "certifications": Certification,
}

# Sections held as one object rather than a list, so an edit to them carries no index.
SINGLETONS = ("basics", "summary")

def edit_model(section: str, model: Type[BaseModel]) -> Type[BaseModel]:
    """An edit whose `values` ARE the model of the section being edited."""
    return create_model(
        f"{model.__name__}Edit",
        section=(Literal[section], Field(description=f"Set when editing the {section} section.")),
        index=(
            int,
            Field(default=0, description="The [n] shown in CURRENT VALUES for this entry, "
                  "e.g. 1 for 'experience[1]'. Always 0 for basics and summary."),
        ),
        values=(
            model,
            Field(description="ONLY the fields they asked to change, with their new values. "
                  "Leave every other field empty — a value you fill in here overwrites what "
                  "is on their resume."),
        ),
    )

SECTION_EDITS = tuple(edit_model(section, model) for section, model in EDITABLE.items())

class EditPlan(BaseModel):
    understood: bool = Field(
        description="True only if the request names a concrete change to a field listed in CURRENT VALUES."
    )
    edits: List[Union[SECTION_EDITS]] = Field(
        default_factory=list,
        description="Changes to apply, one per section touched. Empty when understood is false.",
    )
    # Defaulted: a missing required field would discard an otherwise good edit.
    reply: str = Field(
        default="",
        description="One short sentence confirming what changed, or asking what they meant if it was unclear. Under 25 words."
    )

def describe_fields(resume: Dict[str, Any]) -> str:
    """A flat `path = value` listing of what's filled in."""
    lines: List[str] = []

    for section in EDITABLE:
        value = resume.get(section)

        if isinstance(value, dict):
            for key, item in value.items():
                if item not in ("", [], {}, None):
                    lines.append(f"{section}.{key} = {item}")

        elif isinstance(value, list):
            for i, entry in enumerate(value):
                if not isinstance(entry, dict):
                    continue
                for key, item in entry.items():
                    if item in ("", [], {}, None):
                        continue
                    if isinstance(item, list):
                        item = ", ".join(str(x) for x in item)
                    lines.append(f"{section}[{i}].{key} = {item}")

    return "\n".join(lines)

def targeted(edit: BaseModel) -> tuple:
    """One typed edit as the (path, values) pair apply_extraction takes."""
    path = edit.section if edit.section in SINGLETONS else f"{edit.section}[{edit.index}]"
    return path, edit.values.model_dump(exclude_defaults=True)

# What each section is called when it is being read back to the person who owns it.
SECTION_NAMES = {
    "basics": "contact details",
    "summary": "summary",
    "skills": "skills",
    "experience": "experience",
    "projects": "projects",
    "education": "education",
    "certifications": "certifications",
}

# Past this a value is prose, and quoting it back is noise rather than confirmation.
QUOTABLE = 40

def human_list(items: List[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    if len(items) < 3:
        return " and ".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"

def confirmation(edits: List[Any]) -> str:
    """What changed, read back off the edits themselves rather than asked for again.

    Naming the fields that were written said "Updated your keywords, keywords." — the
    internal name of the field, twice, because two skills were added. What someone wants
    to hear is what they just asked for, in the words they asked for it in.
    """
    if not edits:
        return "Done."

    sections, said = [], []
    for edit in edits:
        sections.append(SECTION_NAMES.get(edit.section, edit.section.replace("_", " ")))
        for value in targeted(edit)[1].values():
            found = value if isinstance(value, list) else [value]
            said += [str(item).strip() for item in found if str(item).strip()]

    where = human_list(list(dict.fromkeys(sections)))
    short = [text for text in dict.fromkeys(said) if len(text) <= QUOTABLE]

    # Only when every value is short enough to quote: half a list read back is worse
    # than none of it, because it looks like the rest was dropped.
    if short and len(short) == len(said):
        return f"Updated your {where} — {human_list(short)}."
    return f"Updated your {where}."

def apply_edit(state: ResumeState) -> Dict[str, Any]:
    """Turns a plain-language change request into a deterministic profile update."""
    logger.info("Applying a user-requested profile edit...")

    instruction = state.get("latest_answer") or ""
    resume = state.get("master_profile", {})
    if hasattr(resume, "model_dump"):
        resume = resume.model_dump()

    def say(text: str, applied: bool) -> Dict[str, Any]:
        return {
            # field "system" so the confirmation does not capture the next turn.
            "current_question": {
                "field": "system",
                "question_text": text,
                "ui": "text",
                "options": [],
            },
            "edit_applied": applied,
            "latest_answer": None,
        }

    current_values = describe_fields(resume)
    if not current_values:
        return say("There's nothing in your resume to change yet — let's fill it in first.", False)

    prompt = EDIT_PLAN.format(current_values=current_values, instruction=instruction)

    try:
        # function_calling: json_schema strict mode would require every field.
        plan: EditPlan = get_openai_llm().with_structured_output(
            EditPlan, method="function_calling"
        ).invoke(prompt)
    except Exception as e:
        logger.error(f"Edit planning failed: {e}")
        return say("I couldn't work out that change — could you rephrase it?", False)

    if not plan.understood or not plan.edits:
        return say(plan.reply or "Which part would you like me to change?", False)

    candidate = resume
    for edit in plan.edits:
        candidate = apply_extraction(candidate, *targeted(edit), None, replace=True)

    try:
        updated = Resume.model_validate(candidate).model_dump()
    except Exception as e:
        logger.warning(f"Edit produced an invalid profile, discarding: {e}")
        return say("That change didn't fit the resume format — could you rephrase it?", False)

    result: Dict[str, Any] = {"master_profile": updated,
                              **say(plan.reply or confirmation(plan.edits), True)}

    # render_resume prefers the tailored copy, so mirror the edit onto it too.
    generated = state.get("generated_resumes") or {}
    tailored = generated.get("tailored")
    if tailored is not None:
        tailored_dict = tailored.model_dump() if hasattr(tailored, "model_dump") else tailored
        for edit in plan.edits:
            tailored_dict = apply_extraction(tailored_dict, *targeted(edit), None, replace=True)
        try:
            generated["tailored"] = Resume.model_validate(tailored_dict).model_dump()
            result["generated_resumes"] = generated
        except Exception as e:
            logger.warning(f"Could not mirror the edit onto the tailored resume: {e}")

    logger.info("Applied %d edit(s): %s", len(plan.edits), [targeted(e)[0] for e in plan.edits])
    return result
