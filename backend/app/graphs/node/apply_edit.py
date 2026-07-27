"""Applies a change the user asked for out loud, to a field that is already filled.

analyze_gaps only ever queues fields that are EMPTY, so once something has a value
nothing in the interview will bring it up again. This node is the way a user says
"change my location to Noida" and has it stick.
"""

import logging
from typing import Any, Dict, List, Literal, Type, Union

from pydantic import BaseModel, Field, create_model

from app.graphs.apply import apply_extraction
from app.graphs.state import (
    Basics, Certification, Education, Experience, Project, Resume, ResumeState,
    SkillCategory, Summary,
)
from app.utils.llm import get_openai_llm

logger = logging.getLogger(__name__)

# Containers a user can reasonably ask to change, and the model each one holds. Bullet
# rewrites go through the normal enhance/tailor path, so highlights are addressed as a
# whole list.
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
    """An edit whose `values` ARE the model of the section being edited.

    A free-form {field: value} dict is a schemaless object: the model may return any key
    it likes, and a key that is not a field of the section is dropped in silence by
    model_validate — while `understood` is still true, so the user is told their location
    changed and nothing changed. Naming the real model makes the wrong key unspellable.
    """
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
    # Defaulted, not required: with the edits themselves carrying a whole section model,
    # gpt-4o-mini fills those in and forgets the sentence — and a missing required field
    # fails validation, throwing away a perfectly good edit over the confirmation text.
    # It is the one field here that can be written without the model, so it is.
    reply: str = Field(
        default="",
        description="One short sentence confirming what changed, or asking what they meant if it was unclear. Under 25 words."
    )


def describe_fields(resume: Dict[str, Any]) -> str:
    """A flat `path = value` listing of what's filled in.

    Sent instead of the whole profile dict: it is smaller, and it hands the model the
    exact path vocabulary that apply_extraction expects back.
    """
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
    """One typed edit as the (path, values) pair apply_extraction takes.

    exclude_defaults is what keeps "they did not mention it" apart from "they want it
    blank": every field of a model comes back present, and writing those blanks over the
    rest of the section is how a change of city empties someone's phone number.

    ponytail: which also means an edit cannot clear a field — "remove my GPA" reads as
    mentioning nothing. Add an explicit `clear: List[str]` to the edit model if anyone
    ever asks for it.
    """
    path = edit.section if edit.section in SINGLETONS else f"{edit.section}[{edit.index}]"
    return path, edit.values.model_dump(exclude_defaults=True)


def confirmation(edits: List[Any]) -> str:
    """What changed, read back off the edits themselves rather than asked for again."""
    changed = [field for edit in edits for field in targeted(edit)[1]]
    return f"Updated your {', '.join(changed)}." if changed else "Done."


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

    prompt = f"""
    The user wants to change something in their resume.

    CURRENT VALUES:
    {current_values}

    THEIR REQUEST: "{instruction}"

    Work out which fields they want changed and what the new values are.
    Give one edit per entry you are changing: its section, the [n] shown above for it,
    and the new values. Fill in ONLY the fields they asked to change and leave the rest
    of that entry empty — anything you fill in overwrites what is on their resume.
    Never invent a value.
    If the request is vague or names something not listed above, set understood to
    false and ask them what they meant.
    """

    try:
        # function_calling, not the default json_schema: strict mode requires every field
        # to be required, and a section model whose fields all default to empty is the
        # whole point — "only what they asked to change" is the fields left unset.
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

    # render_resume prefers the tailored version, so an edit that only touched the
    # master would never show up in the PDF the user is looking at.
    generated = state.get("generated_resumes") or {}
    tailored = generated.get("tailored")
    if tailored is not None:
        tailored_dict = tailored.model_dump() if hasattr(tailored, "model_dump") else tailored
        for edit in plan.edits:
            tailored_dict = apply_extraction(tailored_dict, *targeted(edit), None, replace=True)
        try:
            generated["tailored"] = Resume.model_validate(tailored_dict)
            result["generated_resumes"] = generated
        except Exception as e:
            logger.warning(f"Could not mirror the edit onto the tailored resume: {e}")

    logger.info("Applied %d edit(s): %s", len(plan.edits), [targeted(e)[0] for e in plan.edits])
    return result


if __name__ == "__main__":
    profile = Resume(**{
        "basics": {"name": "Suraj Patel", "location": "Lucknow", "email": "s@example.com"},
        "experience": [{"company": "Careerboat", "position": "Full Stack Engineer",
                        "highlights": ["Built APIs", "Shipped features"]}],
        "skills": [{"name": "Languages", "keywords": ["Python", "Go"]}],
    }).model_dump()

    described = describe_fields(profile)

    # The model can only target what it is shown, so every filled field must appear.
    assert "basics.location = Lucknow" in described, described
    assert "experience[0].company = Careerboat" in described, described
    assert "skills[0].keywords = Python, Go" in described, "list values must be readable"

    # Empty fields are noise — they cost tokens and invite edits to nothing.
    assert "basics.website" not in described, described
    assert "gpa" not in described, described

    # Every section it is shown is a section it can name back, or the edit has nowhere
    # to land and the user is told about a change that never happened.
    assert {e.model_fields["section"].annotation.__args__[0] for e in SECTION_EDITS} == set(EDITABLE)

    def edit(section, **kw):
        """The plan an edit request comes back as, built the way pydantic would."""
        model = next(e for e in SECTION_EDITS
                     if e.model_fields["section"].annotation.__args__[0] == section)
        return model(section=section, **kw)

    # A singleton section carries no index; a list section carries the one it was shown.
    assert targeted(edit("basics", values=Basics(location="Noida"))) \
        == ("basics", {"location": "Noida"}), "only the field they named, and no index"
    assert targeted(edit("experience", index=1, values=Experience(company="Acme")))[0] \
        == "experience[1]"

    # The pair goes straight into apply_extraction, and touches nothing else.
    path, values = targeted(edit("basics", values=Basics(location="Noida")))
    updated = Resume.model_validate(apply_extraction(profile, path, values, None, replace=True))
    assert updated.basics.location == "Noida"
    assert updated.basics.name == "Suraj Patel", "unrelated fields must survive"

    path, values = targeted(edit("experience", values=Experience(company="Acme")))
    updated = Resume.model_validate(apply_extraction(profile, path, values, None, replace=True))
    assert updated.experience[0].company == "Acme"
    assert updated.experience[0].position == "Full Stack Engineer", "siblings must survive"
    assert updated.experience[0].highlights == ["Built APIs", "Shipped features"]

    # A rewritten list replaces what was there. Appending is right when the interview is
    # collecting bullets; here it would leave the line the user asked to change in place.
    path, values = targeted(edit("experience", values=Experience(highlights=["Shipped the API"])))
    updated = Resume.model_validate(apply_extraction(profile, path, values, None, replace=True))
    assert updated.experience[0].highlights == ["Shipped the API"], updated.experience[0].highlights

    assert describe_fields(Resume().model_dump()) == "", "an empty profile describes as nothing"

    print("apply_edit ok")