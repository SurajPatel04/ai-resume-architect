import json
import logging
from typing import Any, Dict
from app.graphs.state import ResumeState
from app.graphs.node.career_setup import CAREER_CHIPS, ROLE_CHIPS
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
    """Everything the candidate has already described doing, in their own words.

    By the time the skills question is asked they have usually described a job and two
    projects naming a dozen technologies each — and the chips they were offered came from
    the role label alone, so someone who had just written "FastAPI, LangGraph, MongoDB,
    FAISS, Redis" was offered Ruby on Rails and Django.
    """
    lines: List[str] = []
    for job in resume.get("experience") or []:
        lines.extend(job.get("highlights") or [])
    for project in resume.get("projects") or []:
        if project.get("description"):
            lines.append(project["description"])
        lines.extend(project.get("highlights") or [])

    return "\n".join(f"- {line}" for line in lines[:20] if str(line).strip())

def role_skill_chips(role: str, evidence: str = "") -> List[str]:
    """Skills to tap for `role`, instead of a blank box to type into.

    ponytail: the model is the taxonomy. At temperature 0 the same role and the same
    resume give the same list, so this behaves like a lookup table nobody has to
    maintain — swap in a static dict if it ever has to work without a network.
    """
    already = f"""
    THEY HAVE ALREADY DESCRIBED DOING THIS:
    {evidence}

    Every technology named above goes in the list FIRST, in the order it matters to the
    role — they have demonstrably used it and being asked to type it again reads as not
    having listened. Fill the remaining slots with what {role} postings commonly ask for.
    """ if evidence.strip() else """
    List the skills that postings for this role name most often — the ones a recruiter
    scans for.
    """

    prompt = f"""
    A candidate is building a resume and is targeting this role: {role}
    {already}
    Concrete tools, languages and frameworks only. No soft skills.

    These are shown as chips to tap, so each one must be the short name it would appear
    as on a resume ("PostgreSQL", not "PostgreSQL database administration").
    """
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
    """What the interview already knows, put in front of the question it asks next.

    The profile JSON *is* the transcript — every answer so far ended up in it, so shipping
    a separate conversation history would be the same facts twice at twice the tokens.
    Only what changes how the next question should read goes in: who they said they are,
    what they're aiming at, and whatever is already recorded for the item being asked about.
    """
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
    """A tap on an affirmative chip, or the typed equivalent.

    Shared with review_quality's gate so "yes" means the same thing everywhere. Anything
    unclear is not a yes — the caller's default is always the cheaper mistake.
    """
    reply = (answer or "").strip().lower().lstrip("*_ ")
    return reply.startswith(("yes", "yeah", "yep", "sure", "ok", "let's", "lets"))

AFFIRMATIONS = frozenset({
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "y", "true", "correct",
    "yes please", "of course", "i do", "let's go", "lets go", "definitely",
})

def is_affirmation(value: Any) -> bool:
    """Is this value just the word the user tapped to say a section exists?

    A gate asks whether a section is there at all, but extract_entities only sees the
    list of missing fields and dutifully answers it — a tap on "Yes" comes back as
    name="Yes", which is how a project called Yes reached someone's resume.
    """
    return str(value or "").strip().strip(".,!").lower() in AFFIRMATIONS

def with_skip(ui: str, options: List[str]) -> tuple:
    """Add the way out, promoting a bare text box to chips over a text box.

    The input box never goes away — "chips" renders the options above it, which is how
    the skills question already offers both a list to tap and somewhere to type.
    """
                                                                                   
    options = list(dict.fromkeys(str(option) for option in (options or []) if str(option).strip()))
    if SKIP_CHIP in options:
        return ui, options
    return ("chips" if ui == "text" else ui), options + [SKIP_CHIP]

class GeneratedQuestion(BaseModel):
    question_text: str = Field(description="The short, polite question to ask the user.")
    ui: Literal["text", "chips"] = Field(description="Use 'chips' if there are 2-5 distinct short options (e.g. Yes/No, or specific skills), otherwise use 'text'.")
    options: List[str] = Field(default_factory=list, description="A list of 2-5 short options if ui is 'chips'.")

def quote_bullet(bullet: Any, question: str) -> str:
    """Put what the resume already says in front of the question that's about it.

    Quoted deterministically rather than asked for in the prompt: the model paraphrases
    ("the real-time audio streaming work") into something the user has to match back to
    a line they wrote months ago, and often can't. The frontend renders markdown.

    Takes one line or several — a follow-up about `highlights` is about every bullet on
    that entry. The blank quote line between them is what makes markdown render them as
    separate lines rather than running them into one paragraph.
    """
    lines = bullet if isinstance(bullet, list) else [bullet]
    lines = [str(line).strip() for line in lines if str(line or "").strip()]
    if not lines:
        return question
    return "Your resume says:\n\n" + "\n>\n".join(f"> {line}" for line in lines) + f"\n\n{question}"

def entry_label(resume: Dict[str, Any], target_gap: Dict[str, Any]) -> str:
    """How to refer to the entry a question is about, in the user's own words.

    "at Acme as an Engineer" beats "at experience[0]", and a question about the one job
    with no dates on a resume that lists four has to say which one it means.
    """
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
    """What the resume currently holds for the fields a follow-up is about.

    A planner follow-up names an item and the fields its answer lands in. Where those
    already hold something — a bullet to sharpen, a date that contradicts another — the
    user has to see it, or they are matching the question against a line they wrote weeks
    ago from memory. Empty fields quote nothing: a follow-up about a missing end date has
    no "your resume says" to show.
    """
    item = current_item(resume, field)
    out: List[str] = []
    for name in fields or []:
        value = item.get(name)
        for line in (value if isinstance(value, list) else [value]):
            if str(line or "").strip():
                out.append(str(line).strip())
    return out

def impact_question(target_gap: Dict[str, Any]) -> str:
    """A deterministic, self-contained question about one exact resume bullet.

    This is deliberately not LLM-written. When asking somebody to substantiate a
    claim, vague phrasing or a paraphrased bullet makes them guess what we mean.
    """
    bullet = target_gap.get("weak_bullet", "")
    reason = str(target_gap.get("reason") or "it does not yet show a clear result").rstrip(".")
    return quote_bullet(
        bullet,
        f"Why it could be stronger: {reason}. What changed after your work? "
        "Share any real result you remember — for example time saved, cost, reliability, "
        "speed, users, conversion, or error reduction.",
    )

def generate_question(state: ResumeState) -> Dict[str, Any]:
    """
    Uses the LLM to generate the natural language question based on active_target.
    Returns the result in state.current_question.
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
    error_context = ""
    if errors:
        error_context = f"\n\nCRITICAL: The user's previous answer for this field failed validation! Error: {errors[-1]}\nYou MUST apologize and politely re-ask the user to provide the information in the correct format."

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
                                                                                      
        return {
            "current_question": {
                "field": target_gap["field"],
                "question_text": impact_question(target_gap),
                "section": "impact",
                "ui": "chips",
                "options": IMPACT_OPTIONS,
                "is_gate": False,
                "skip_section_if_empty": False,
                "missing_fields": target_gap.get("missing_fields", []),
                "bullet_index": target_gap.get("bullet_index"),
            },
        }
    else:
        instructions = f"""
    The user's resume is missing specific fields for the item {target_gap['field']}.
    Specifically, these fields are missing and need to be filled: {missing_str}.
    Reason: {target_gap['reason']}
    
    Ask a short, conversational question to gather ONLY these missing fields: {missing_str}.
    Do NOT ask for fields that are already filled. Combine the request for these missing fields into one smooth question.

    If the requested fields have clear, common answers (like 3-5 common skills for their role), set ui to 'chips' and provide those as options.
    Otherwise, if it requires a free-text response, set ui to 'text' and leave options empty.
        """

    prompt = f"""
    You are an expert resume assistant.
    {error_context}

    {known_context(state, target_gap['field'])}

    {instructions}

    Never re-ask for anything listed as already recorded above, and word the question so it
    fits what you already know about them.
    Keep the question polite and under 2 sentences.
    """

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

if __name__ == "__main__":
    from app.graphs.node.career_setup import read_career_level, read_target_role

    assert IMPACT_OPTIONS == ["I don't have a number", "Skip this one"]

    for option in IMPACT_OPTIONS:
        assert "%" not in option, option
        assert not any(ch.isdigit() for ch in option), f"a magnitude leaked into the chips: {option}"

    gate = generate_question({"active_target": {
        "field": "experience[0]", "section": "experience", "is_gate": True,
        "missing_fields": ["company", "position", "highlights"],
    }})["current_question"]
    assert gate["ui"] == "chips" and gate["options"] == [YES_CHIP, NO_CHIP]
    assert gate["question_text"] == "Do you have any work experience to add?"
    assert gate["is_gate"] is True, "validate_entities keys the slot-opening off this"
    assert len(gate["question_text"].split()) < 12

    from app.graphs.node.analyze_gaps import MORE_FIELDS, more_gate

    for section in MORE_FIELDS:
        again = generate_question({"active_target": more_gate(section, 1)})["current_question"]
        first = generate_question({"active_target": {
            "field": f"{section}[0]", "section": section, "is_gate": True,
            "missing_fields": MORE_FIELDS[section],
        }})["current_question"]
        assert again["question_text"] != first["question_text"], section
        assert "other" in again["question_text"].lower(), again["question_text"]
        assert again["options"] == [YES_CHIP, NO_CHIP], again["options"]
                                                                                   
        assert again["is_gate"] is True and again["field"] == f"{section}[1]"

    SKILLS_GAP = {"field": "skills", "section": "skills", "is_gate": True,
                  "missing_fields": ["skills"]}
    skills_gate = generate_question({"active_target": SKILLS_GAP})["current_question"]
    assert "skills" in skills_gate["question_text"].lower()
    assert YES_CHIP not in skills_gate["options"], "a yes/no here would cost a turn for nothing"
                                                                                 
    assert skills_gate["ui"] == "chips" and skills_gate["options"] == ["Skip this"]

    level_q = generate_question({"active_target": {
        "field": "career_level", "section": "career_level", "is_gate": True, "missing_fields": [],
    }})["current_question"]
    assert level_q["options"] == list(CAREER_CHIPS), level_q["options"]
    for label in level_q["options"]:
        assert read_career_level(label), f"offered a chip nobody can parse: {label}"

    role_q = generate_question({"active_target": {
        "field": "target_role", "section": "target_role", "is_gate": True, "missing_fields": [],
    }})["current_question"]
    assert role_q["options"] == list(ROLE_CHIPS)
    assert "type" in role_q["question_text"].lower(), "a closed list of roles is a dead end"
    for label in role_q["options"]:
        assert read_target_role(label) == label

    PROFILE = {
        "basics": {"name": "Priya", "email": "", "phone": ""},
        "experience": [{"company": "Acme", "position": "", "highlights": []}],
        "education": [], "projects": [], "skills": [],
    }
    ctx = known_context(
        {"master_profile": PROFILE, "career_level": "experienced", "target_role": "Backend Engineer"},
        "experience[0]",
    )
    assert "experienced" in ctx and "Backend Engineer" in ctx
    assert "Acme" in ctx, "the question must know what's already on the entry it's asking about"
    assert "position" not in ctx, "empty fields are what we're asking for, not context"
    assert "Sections already recorded: experience" in ctx
    assert known_context({}, "basics") == "", "nothing known yet, nothing to say"

    BUILT = {
        "experience": [{"highlights": ["Cut LLM token consumption 40% with Node.js and MongoDB"]}],
        "projects": [{"description": "Multimodal RAG Platform",
                      "highlights": ["Built on FastAPI, LangGraph, React, FAISS and Redis"]}],
    }
    evidence = used_technologies(BUILT)
    for named in ("Node.js", "MongoDB", "FastAPI", "LangGraph", "FAISS", "Multimodal RAG"):
        assert named in evidence, named
    assert used_technologies({}) == "", "nothing described yet, nothing to draw on"
    assert used_technologies({"experience": [{"highlights": []}]}) == ""
                                                                                        
    assert len(used_technologies({"projects": [
        {"highlights": [f"Did thing {i}" for i in range(50)]}]}).splitlines()) == 20

    assert current_item(PROFILE, "experience[0]")["company"] == "Acme"
    assert current_item(PROFILE, "experience[7]") == {}, "an index past the end is not a crash"
    assert current_item(PROFILE, "basics")["name"] == "Priya"
    assert current_item(PROFILE, "skills") == {}, "a list section has no single entry"

    assert says_yes("Yes") and says_yes("yeah ok") and says_yes(IMPACT_OPTIONS[0]) is False
    assert not says_yes("No, skip this") and not says_yes("") and not says_yes("not really")

    for tap in ("Yes", "yeah", " OK ", "Sure.", "YES", "yes please", "Correct", "y"):
        assert is_affirmation(tap), tap
    for real in ("Okta", "Yesware", "Sure Retail Ltd", "Amity University", "tata", ""):
        assert not is_affirmation(real), real
    assert says_yes("Okta"), "says_yes is prefix-matched — which is exactly why it is not used here"

    assert with_skip("text", []) == ("chips", [SKIP_CHIP])
    assert with_skip("chips", ["A", "B"]) == ("chips", ["A", "B", SKIP_CHIP])
    assert with_skip("chips", [SKIP_CHIP]) == ("chips", [SKIP_CHIP]), "never offered twice"
    assert with_skip("multi_select", ["Python"])[0] == "multi_select", "the skills list stays a list"

    invented = generate_question({"active_target": {
        "field": "projects[0]", "section": "projects", "missing_fields": ["highlights"],
        "question_text": "What did the project actually do?",
    }})["current_question"]
    assert invented["options"] == [SKIP_CHIP] and invented["ui"] == "chips"
    assert invented["question_text"] == "What did the project actually do?", "written by the planner, not reworded"

    WRITTEN = {**PROFILE, "experience": [
        {"company": "Acme", "position": "", "highlights": ["Built things", "Shipped the thing"]},
    ]}
    quoted = generate_question({"master_profile": WRITTEN, "active_target": {
        "field": "experience[0]", "section": "experience", "missing_fields": ["highlights"],
        "question_text": "Which of these had a number attached?",
    }})["current_question"]
    assert "> Built things" in quoted["question_text"], quoted["question_text"]
    assert "> Shipped the thing" in quoted["question_text"], "every bullet on the entry, not just the first"
    assert quoted["question_text"].endswith("Which of these had a number attached?")

    bare = generate_question({"master_profile": PROFILE, "active_target": {
        "field": "experience[0]", "section": "experience", "missing_fields": ["end_date"],
        "question_text": "When did you leave?",
    }})["current_question"]
    assert bare["question_text"] == "When did you leave?", bare["question_text"]

    DATED = {**PROFILE, "experience": [
        {"company": "Acme", "position": "Engineer", "highlights": ["Built things"]},
    ], "education": [{"institution": "Amity University", "study_type": "MCA"}]}

    dates = generate_question({"master_profile": DATED, "active_target": {
        "field": "experience[0]", "section": "experience",
        "missing_fields": ["start_date", "end_date"],
    }})["current_question"]
    assert dates["ui"] == "dates", dates
    assert dates["options"] == [SKIP_CHIP], "a job nobody can date must not be a dead end"
    assert "Engineer at Acme" in dates["question_text"], dates["question_text"]

    assert generate_question({"master_profile": DATED, "active_target": {
        "field": "experience[0]", "section": "experience", "missing_fields": ["end_date"],
    }})["current_question"]["ui"] == "dates"

    both = generate_question({"master_profile": DATED, "active_target": {
        "field": "experience[0]", "section": "experience",
        "missing_fields": ["start_date", "end_date", "highlights"],
    }})["current_question"]
    assert both["ui"] == "chips" and "bullet points" in both["question_text"], both

    assert "Amity University" in generate_question({"master_profile": DATED, "active_target": {
        "field": "education[0]", "section": "education", "missing_fields": ["end_date"],
    }})["current_question"]["question_text"]

    assert entry_label({}, {"field": "experience[3]", "section": "experience"}) == "there",\
        "an entry with nothing on it yet still has to be referred to somehow"

    assert recorded_values(PROFILE, "basics", ["name"]) == ["Priya"]
    assert recorded_values(PROFILE, "experience[9]", ["company"]) == [], "a path past the end quotes nothing"
    assert recorded_values(PROFILE, "experience[0]", []) == []

    assert SKIP_CHIP not in IMPACT_OPTIONS, "impact has its own wording for this"

    asked = quote_bullet("Orchestrated TTS, AWS S3, and SSE", "What changed?")
    assert "> Orchestrated TTS, AWS S3, and SSE" in asked, asked
    assert asked.endswith("What changed?")
    assert quote_bullet("", "What changed?") == "What changed?", "no bullet, no blockquote"
    impact = impact_question({"weak_bullet": "Integrated Razorpay payments", "reason": "has no measurable result"})
    assert "> Integrated Razorpay payments" in impact
    assert "Why it could be stronger: has no measurable result" in impact

    print("generate_question ok")
