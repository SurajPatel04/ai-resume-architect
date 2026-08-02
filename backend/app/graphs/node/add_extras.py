"""The last thing asked before the resume is built: anything else to add?"""

import logging
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.graphs.node.skill_gap import ClaimedSkill, add_skills
from app.graphs.node.render_resume import custom_titles
from app.graphs.state import Certification, CustomEntry, Education, Resume, ResumeState
from app.graphs.prompts import (
    CERTIFICATION_ISSUERS, DEGREE_SUGGESTIONS, EXTRA_SKILLS, PARSE_CERTIFICATIONS,
    PARSE_CUSTOM_ENTRIES,
    PARSE_EDUCATION,
    PARSE_EXTRA_SKILLS,
)
from app.utils.llm import get_openai_llm

logger = logging.getLogger(__name__)

GATE_SECTION = "add_extras"

CERT_CHIP = "Add certifications"
SKILLS_CHIP = "Add more skills"
DONE_CHIP = "No, I'm done"
AWS_ISSUER_CHIP = "AWS"
GCP_ISSUER_CHIP = "Google Cloud (GCP)"
AZURE_ISSUER_CHIP = "Microsoft Azure"
OTHER_ISSUER_CHIP = "Other / type issuer"
SKIP_LINK_CHIP = "Skip credential link"

EDU_CHIP = "Add education"
OTHER_SECTION_CHIP = "Add another section"
OTHER_DEGREE_CHIP = "Other / type it"

EDU_LEVELS = ("Class 10", "Class 12", "Diploma", "Bachelor's", "Master's", "Doctorate")

# The fallback list, used only when the model cannot be reached. Deliberately thin and
# India-centric: enumerating every qualification in the world is the job this hands to
# the model, and a static table that tried would be wrong for most people who read it.
DEGREES_BY_LEVEL = {
    "Class 10": ["Secondary School Certificate (SSC)", "CBSE Class 10", "ICSE", "State Board Class 10"],
    "Class 12": ["Higher Secondary Certificate (HSC)", "CBSE Class 12", "ISC", "State Board Class 12"],
    "Diploma": ["Diploma in Engineering", "Polytechnic Diploma", "Diploma in Computer Applications"],
    "Bachelor's": ["B.Tech", "B.E.", "B.Sc", "BCA", "B.Com", "BBA", "BA"],
    "Master's": ["M.Tech", "M.Sc", "MCA", "MBA", "MA", "M.Com"],
    "Doctorate": ["PhD", "M.Phil"],
}

# Same: a fallback ordering for the handful of bachelor's degrees named here.
MASTERS_AFTER = (
    (("b.tech", "btech", "b.e.", "bachelor of engineering", "bachelor of technology"),
     ["M.Tech", "M.S.", "MBA", "M.Sc"]),
    (("bca", "bachelor of computer applications"), ["MCA", "M.Sc (IT)", "MBA"]),
    (("b.sc", "bsc", "bachelor of science"), ["M.Sc", "MCA", "MBA", "M.Tech"]),
    (("b.com", "bcom", "bachelor of commerce"), ["M.Com", "MBA", "CA"]),
    (("bba", "bachelor of business"), ["MBA", "PGDM", "M.Com"]),
    (("bachelor of arts",), ["MA", "MBA", "MSW"]),
    (("b.pharm", "bpharm"), ["M.Pharm", "MBA"]),
)

LEVEL_QUESTION = {
    "Class 10": "Which board was that?",
    "Class 12": "Which board was that?",
    "Diploma": "Which diploma is it?",
    "Bachelor's": "Which bachelor's degree is it?",
    "Master's": "Which master's degree is it?",
    "Doctorate": "Which doctorate is it?",
}

def held_degrees(resume: Dict[str, Any]) -> str:
    """Everything already recorded under education, as one lowercase haystack."""
    return " ".join(
        f"{entry.get('study_type', '')} {entry.get('area', '')}"
        for entry in (resume.get("education") or []) if isinstance(entry, dict)
    ).casefold()

MAX_DEGREE_CHIPS = 8

DEGREE_NAME_MAX = 60

def fallback_degrees(level: str, resume: Dict[str, Any]) -> List[str]:
    """The static list, for when the model cannot be reached."""
    generic = list(DEGREES_BY_LEVEL.get(level, []))
    if level != "Master's":
        return generic

    held = held_degrees(resume)
    for words, follows in MASTERS_AFTER:
        if any(word in held for word in words):
            return follows + [d for d in generic if d not in follows]
    return generic

def usable_degrees(names: List[str]) -> List[str]:
    """The model's list, deduped and stripped of anything that is not a degree name.

    These become chips, and whichever one is tapped is written to the resume verbatim —
    so a sentence, an empty string or a repeat has to be caught here rather than printed
    under Education.
    """
    out: List[str] = []
    seen = set()
    for name in names or []:
        label = (name or "").strip().strip(".,")
        key = label.casefold()
        if label and len(label) <= DEGREE_NAME_MAX and key not in seen:
            out.append(label)
            seen.add(key)
    return out[:MAX_DEGREE_CHIPS]

def degree_suggestions(level: str, resume: Dict[str, Any]) -> List[str]:
    """Qualifications to offer at `level`, given what the candidate already holds.

    Asked rather than looked up. A table can only ever name the degrees whoever wrote it
    thought of — this one knew B.Sc and B.Tech and had nothing for LLB, MBBS or B.Arch,
    and a list that does not contain your degree is a list you have to read past before
    typing it anyway. The static table survives as the answer when the call fails.
    """
    held = held_degrees(resume).strip()

    try:
        result: SuggestedDegrees = get_openai_llm().with_structured_output(
            SuggestedDegrees, method="function_calling"
        ).invoke(DEGREE_SUGGESTIONS.format(
            level=level, held=held or "nothing recorded yet"
        ))
    except Exception as e:
        logger.warning("Could not suggest %s degrees, using the static list: %r", level, e)
        return fallback_degrees(level, resume)

    names = usable_degrees(result.degrees)
    if not names:
        return fallback_degrees(level, resume)

    logger.info("Suggested %s after %r: %s", level, held or "nothing", ", ".join(names))
    return names

ISSUER_BY_CHIP = {
    AWS_ISSUER_CHIP: "Amazon Web Services (AWS)",
    GCP_ISSUER_CHIP: "Google Cloud",
    AZURE_ISSUER_CHIP: "Microsoft Azure",
}

# Credentials that name their own issuer. "AWS Cloud Practitioner" was never a question:
# asking who issued it, and offering AWS among the answers, is asking someone to repeat
# the word they just typed.
ISSUER_BY_NAME = (
    (("aws", "amazon web services"), "Amazon Web Services (AWS)"),
    (("gcp", "google cloud"), "Google Cloud"),
    (("azure",), "Microsoft Azure"),
    (("oracle",), "Oracle"),
    (("cisco", "ccna", "ccnp"), "Cisco"),
    (("comptia", "security+"), "CompTIA"),
    (("salesforce",), "Salesforce"),
    (("cka", "ckad", "kubernetes"), "Cloud Native Computing Foundation (CNCF)"),
    (("pmp", "capm"), "Project Management Institute (PMI)"),
    (("red hat", "rhce"), "Red Hat"),
    (("databricks",), "Databricks"),
    (("tableau",), "Tableau"),
    (("cissp", "isc2"), "ISC2"),
)

def issuer_from_name(name: str) -> str:
    """The issuer a credential names itself, or "" when it names none or several.

    Several means ask: "AWS and Azure fundamentals" has two answers and picking one
    would put an issuer on someone's resume that they did not choose.
    """
    lowered = (name or "").casefold()
    hits = {issuer for words, issuer in ISSUER_BY_NAME if any(w in lowered for w in words)}
    return hits.pop() if len(hits) == 1 else ""

class ParsedCertifications(BaseModel):
    certifications: List[Certification] = Field(
        default_factory=list,
        description="One entry per certification, licence or award the user named. Copy what they "
        "wrote — never invent an issuer, date, or credential URL they did not give.",
    )

class ParsedEducation(BaseModel):
    education: List[Education] = Field(
        default_factory=list,
        description="One entry per qualification the user named. Copy what they wrote — never "
        "invent an institution, dates, or a grade they did not give.",
    )

class ParsedCustomEntries(BaseModel):
    entries: List[CustomEntry] = Field(
        default_factory=list,
        description="One entry per thing the user named. Copy what they wrote — never invent an "
        "organisation, a date, or bullet points they did not give.",
    )

class ParsedSkills(BaseModel):
    skills: List[ClaimedSkill] = Field(
        default_factory=list,
        description="One entry per skill the user named, filed under one of their existing "
        "categories where it fits.",
    )

class SuggestedExtraSkills(BaseModel):
    skills: List[str] = Field(
        default_factory=list,
        description="Short, concrete skills the candidate may have but has not listed yet."
    )

class SuggestedDegrees(BaseModel):
    degrees: List[str] = Field(
        default_factory=list,
        description="Qualifications at the requested level, most likely first. Short names as they "
        "would be written on a resume — 'M.Tech', not 'Master of Technology degree programme'.",
    )

class SuggestedCertificationIssuers(BaseModel):
    issuers: List[str] = Field(
        default_factory=list,
        description="Likely organizations that issue the named certification. These are choices, not claims about the candidate.",
    )

def _question(text: str, step: str, ui: str = "text", options: List[str] = None) -> Dict[str, Any]:
    return {
        "field": GATE_SECTION,
        "section": GATE_SECTION,
        "question_text": text,
        "ui": ui,
        "options": options if options is not None else [DONE_CHIP],
        "is_gate": False,
        "missing_fields": [],
        "bullet_index": None,

        "step": step,
    }

def more_chip(name: str) -> str:
    return f"Add more {name}"

def gate(prefix: str = "", resume: Dict[str, Any] = None) -> Dict[str, Any]:
    """The one question. `prefix` acknowledges what was just added.

    The chips follow the resume rather than a fixed list. Someone whose document had a
    Volunteering section gets offered Volunteering, because that is a section they
    evidently keep — and otherwise the only way to add to it would be knowing that you
    can.
    """
    extra = [more_chip(name) for name in custom_titles(resume or {})]
    return _question(
        f"{prefix}Anything else to add before I build your resume?",
        step="gate",
        ui="chips",
        options=[CERT_CHIP, SKILLS_CHIP, EDU_CHIP] + extra + [OTHER_SECTION_CHIP, DONE_CHIP],
    )

def keep_certifications(parsed: List[Certification]) -> List[Dict[str, Any]]:
    """Drop entries with no name — a certification with only a date is noise on a resume."""
    return [c.model_dump() for c in parsed if (c.name or "").strip()]

def _with_pending(question: Dict[str, Any], certifications: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Keep an unfinished credential on the question, like other short multi-step flows."""
    return {**question, "pending_certifications": certifications}

def suggested_certification_issuers(certifications: List[Dict[str, Any]]) -> List[str]:
    """Offer likely issuers for any credential type; the candidate must still choose one."""
    names = " ".join(str(cert.get("name", "")) for cert in certifications).casefold()
    known_matches = (
        (("aws", "amazon web services", "cloud practitioner"), [AWS_ISSUER_CHIP, GCP_ISSUER_CHIP, AZURE_ISSUER_CHIP]),
        (("google", "gcp"), [GCP_ISSUER_CHIP, AWS_ISSUER_CHIP, AZURE_ISSUER_CHIP]),
        (("azure", "microsoft"), [AZURE_ISSUER_CHIP, GCP_ISSUER_CHIP, AWS_ISSUER_CHIP]),
        (("scrum", "agile"), ["Scrum Alliance", "Scrum.org", "Project Management Institute (PMI)"]),
        (("pmp", "capm", "project management"), ["Project Management Institute (PMI)"]),
        (("java", "oracle"), ["Oracle"]),
        (("kubernetes", "cka", "ckad"), ["Cloud Native Computing Foundation (CNCF)"]),
        (("cissp", "isc2", "security+", "comptia", "ceh"), ["ISC2", "CompTIA", "EC-Council"]),
        (("cisco", "ccna", "ccnp"), ["Cisco"]),
        (("salesforce",), ["Salesforce"]),
        (("linux", "red hat", "rhce"), ["Linux Foundation", "Red Hat"]),
        (("databricks", "tableau", "data analytics"), ["Databricks", "Tableau", "Microsoft"]),
    )
    suggestions = [issuer for words, issuers in known_matches if any(word in names for word in words) for issuer in issuers]

    try:
        result: SuggestedCertificationIssuers = get_openai_llm().with_structured_output(
            SuggestedCertificationIssuers, method="function_calling"
        ).invoke(CERTIFICATION_ISSUERS.format(names=names or "unspecified certification"))
        suggestions.extend(result.issuers)
    except Exception as e:
        logger.warning("Could not generate certification issuer suggestions: %r", e)

    unique: List[str] = []
    seen = set()
    for issuer in suggestions:
        label = (issuer or "").strip()
        # Deduped by what the chip MEANS: "AWS" and "Amazon Web Services (AWS)" are one
        # answer, and offering both makes the list read as two different issuers.
        key = ISSUER_BY_CHIP.get(label, label).casefold()
        if label and key not in seen:
            unique.append(label)
            seen.add(key)
    return unique[:5]

def _issuer_question(certifications: List[Dict[str, Any]]) -> Dict[str, Any]:
    names = ", ".join(cert["name"] for cert in certifications if not cert.get("issuer"))
    choices = suggested_certification_issuers(certifications)
    return _with_pending(_question(
        f"Which organization issued {names}? Choose a suggestion or type another issuer.",
        step="certification_issuer",
        ui="chips",
        options=choices + [OTHER_ISSUER_CHIP, DONE_CHIP],
    ), certifications)

def _credential_link_question(certifications: List[Dict[str, Any]]) -> Dict[str, Any]:
    names = ", ".join(cert["name"] for cert in certifications)
    return _with_pending(_question(
        f"Paste the public credential verification link for {names}, if you have one.",
        step="certification_link",
        ui="chips",
        options=[SKIP_LINK_CHIP, DONE_CHIP],
    ), certifications)

def suggested_extra_skills(resume: Dict[str, Any], role: str = "") -> List[str]:
    """Offer a short set of relevant skills that are not already on the profile."""
    existing = {
        str(keyword).strip().casefold()
        for category in (resume.get("skills") or []) if isinstance(category, dict)
        for keyword in (category.get("keywords") or []) if str(keyword).strip()
    }
    context = role or "the candidate's existing experience"
    try:
        result: SuggestedExtraSkills = get_openai_llm().with_structured_output(
            SuggestedExtraSkills, method="function_calling"
        ).invoke(EXTRA_SKILLS.format(
            context=context, existing=", ".join(sorted(existing)) or "none"
        ))
    except Exception as e:
        logger.warning("Could not generate extra-skill suggestions: %r", e)
        return []

    suggestions: List[str] = []
    seen = set(existing)
    for skill in result.skills:
        name = (skill or "").strip()
        if name and name.casefold() not in seen:
            suggestions.append(name)
            seen.add(name.casefold())
    return suggestions[:8]

def add_extras(state: ResumeState) -> Dict[str, Any]:
    """Offer the sections nothing else can reach, and fold in whatever the user names."""
    pending = state.get("current_question") or {}
    answer = (state.get("latest_answer") or "").strip()

    resume = state.get("master_profile", {})
    if hasattr(resume, "model_dump"):
        resume = resume.model_dump()

    if not (answer and pending.get("section") == GATE_SECTION):
        logger.info("Offering the final additions.")
        return {"extras_offered": True, "current_question": gate("", resume)}

    done: Dict[str, Any] = {"latest_answer": None, "current_question": None}
    step = pending.get("step")

    if answer == DONE_CHIP:
        logger.info("Nothing more to add.")
        return done

    if step == "gate":
        if answer == CERT_CHIP:
            return {**done, "current_question": _question(
                "Tell me your certification name, issuer, earned date, and credential link if you have it. "
                "For a cloud certification, you can simply say \"cloud certification\" and choose AWS, GCP, or Azure next.",
                step="certifications",
            )}
        if answer == EDU_CHIP:
            return {**done, "current_question": _question(
                "Which qualification is it?",
                step="education_level",
                ui="chips",
                options=list(EDU_LEVELS) + [OTHER_DEGREE_CHIP, DONE_CHIP],
            )}
        if answer == OTHER_SECTION_CHIP:
            return {**done, "current_question": _question(
                "What should the section be called? For example Volunteering, Awards, "
                "Publications, or Languages.",
                step="custom_name",
            )}

        named = next((name for name in custom_titles(resume) if answer == more_chip(name)), "")
        if named:
            return {**done, "current_question": _custom_entry_question(named)}

        if answer == SKILLS_CHIP:
            suggestions = suggested_extra_skills(resume, state.get("target_role") or "")
            return {**done, "current_question": _question(
                "Tap a suggested skill you genuinely have, or type additional skills separated "
                "by commas. I will add only the skills you confirm.",
                step="skills",
                ui="chips",
                options=suggestions + [DONE_CHIP],
            )}

        return {**done, "current_question": gate()}

    if step == "custom_name":
        name = answer.strip().strip(".:").title()
        if not name or len(name) > 40:
            return {**done, "current_question": gate("I didn't catch a section name. ", resume)}
        return {**done, "current_question": _custom_entry_question(name)}

    if step == "custom_entries":
        return _add_custom(resume, pending.get("custom_name") or "", answer, done)

    if step == "certifications":
        return _add_certifications(resume, answer, done)

    if step == "education_level":
        if answer == OTHER_DEGREE_CHIP or answer not in EDU_LEVELS:
            return {**done, "current_question": _question(
                "What is the qualification called?", step="education_degree",
            )}
        return {**done, "current_question": _question(
            LEVEL_QUESTION.get(answer, "Which one is it?"),
            step="education_degree",
            ui="chips",
            options=degree_suggestions(answer, resume) + [OTHER_DEGREE_CHIP],
        )}

    if step == "education_degree":
        if answer == OTHER_DEGREE_CHIP:
            return {**done, "current_question": _question(
                "What is the qualification called?", step="education_degree",
            )}
        question = _question(
            f"Which institution was that at, and which years? For example "
            f"\"Amity University, 2024 to 2026\".",
            step="education_where",
        )
        return {**done, "current_question": {**question, "degree": answer.strip()}}

    if step == "education_where":
        return _add_education(resume, answer, done, pending.get("degree") or "")

    pending_certifications = pending.get("pending_certifications") or []
    if step == "certification_issuer":
        if answer == OTHER_ISSUER_CHIP:
            return {**done, "current_question": _with_pending(_question(
                "Which organization issued it? Type the issuer name.",
                step="certification_custom_issuer",
            ), pending_certifications)}

        issuer = ISSUER_BY_CHIP.get(answer, answer)
        completed = [{**cert, "issuer": cert.get("issuer") or issuer} for cert in pending_certifications]
        return {**done, "current_question": _credential_link_question(completed)}

    if step == "certification_custom_issuer":
        completed = [{**cert, "issuer": cert.get("issuer") or answer} for cert in pending_certifications]
        return {**done, "current_question": _credential_link_question(completed)}

    if step == "certification_link":
        completed = pending_certifications if answer == SKIP_LINK_CHIP else [
            {**cert, "url": cert.get("url") or answer} for cert in pending_certifications
        ]
        return _save_certifications(resume, completed, done)

    if step == "skills":
        return _add_skills(resume, answer, done)

    return done

def _add_certifications(resume: Dict[str, Any], answer: str, done: Dict[str, Any]) -> Dict[str, Any]:
    try:
        parsed: ParsedCertifications = get_openai_llm().with_structured_output(
            ParsedCertifications, method="function_calling"
        ).invoke(PARSE_CERTIFICATIONS.format(answer=answer))
    except Exception as e:
        logger.error("Could not read the certifications answer: %r", e)
        return {**done, "current_question": gate("I didn't catch that. ", resume)}

    fresh = keep_certifications(parsed.certifications)
    if not fresh:
        return {**done, "current_question": gate("I didn't catch a certification there. ", resume)}

    # Read the issuer off the name before asking for it.
    fresh = [{**cert, "issuer": cert.get("issuer") or issuer_from_name(cert.get("name", ""))}
             for cert in fresh]

    if any(not cert.get("issuer") for cert in fresh):
        return {**done, "current_question": _issuer_question(fresh)}

    if any(not cert.get("url") for cert in fresh):
        return {**done, "current_question": _credential_link_question(fresh)}

    return _save_certifications(resume, fresh, done)

def _custom_entry_question(name: str) -> Dict[str, Any]:
    question = _question(
        f"What should go under {name}? Give the title, who it was with, the date, and "
        "anything worth saying about it.",
        step="custom_entries",
    )
    return {**question, "custom_name": name}

def _add_custom(resume: Dict[str, Any], name: str, answer: str,
                done: Dict[str, Any]) -> Dict[str, Any]:
    """Fold entries into a section this schema does not model, creating it if needed."""
    if not name:
        return {**done, "current_question": gate("", resume)}

    try:
        parsed: ParsedCustomEntries = get_openai_llm().with_structured_output(
            ParsedCustomEntries, method="function_calling"
        ).invoke(PARSE_CUSTOM_ENTRIES.format(section=name, answer=answer))
    except Exception as e:
        logger.error("Could not read the %s answer: %r", name, e)
        return {**done, "current_question": gate("I didn't catch that. ", resume)}

    fresh = [e.model_dump() for e in parsed.entries
             if (e.title or "").strip() or e.highlights]
    if not fresh:
        return {**done, "current_question": gate(f"I didn't catch anything for {name}. ", resume)}

    sections = [dict(s) for s in (resume.get("custom_sections") or []) if isinstance(s, dict)]
    existing = next((s for s in sections
                     if str(s.get("name", "")).casefold() == name.casefold()), None)
    if existing:
        existing["entries"] = list(existing.get("entries") or []) + fresh
    else:
        sections.append({"name": name, "entries": fresh})

    candidate = {**resume, "custom_sections": sections}
    try:
        updated = Resume.model_validate(candidate).model_dump()
    except Exception as e:
        logger.warning("%s failed validation, discarding: %r", name, e)
        return {**done, "current_question": gate("That didn't fit the resume format. ", resume)}

    titles = ", ".join(e.get("title") or name for e in fresh)
    logger.info("Added %s under %s.", titles, name)
    return {**done, "master_profile": updated,
            "current_question": gate(f"Added {titles} under {name}. ", updated)}

def _add_education(resume: Dict[str, Any], answer: str, done: Dict[str, Any],
                   degree: str = "") -> Dict[str, Any]:
    try:
        parsed: ParsedEducation = get_openai_llm().with_structured_output(
            ParsedEducation, method="function_calling"
        ).invoke(PARSE_EDUCATION.format(answer=answer))
    except Exception as e:
        logger.error("Could not read the education answer: %r", e)
        return {**done, "current_question": gate("I didn't catch that. ", resume)}

    fresh = [e.model_dump() for e in parsed.education
             if (e.institution or "").strip() or (e.study_type or "").strip() or degree]
    if not fresh and degree:
        # They picked the degree off a list and typed only where and when; a parse that
        # found no qualification in "Amity University, 2024 to 2026" is right about that.
        fresh = [Education().model_dump()]
    if not fresh:
        return {**done, "current_question": gate("I didn't catch a qualification there. ", resume)}

    if degree:
        # Theirs by choice, not by parse — the chip they tapped is the exact wording.
        fresh = [{**entry, "study_type": degree} for entry in fresh]

    candidate = dict(resume)
    candidate["education"] = list(candidate.get("education") or []) + fresh

    try:
        updated = Resume.model_validate(candidate).model_dump()
    except Exception as e:
        logger.warning("Education failed validation, discarding: %r", e)
        return {**done, "current_question": gate("That didn't fit the resume format. ", resume)}

    names = ", ".join(e.get("study_type") or e.get("institution") for e in fresh)
    logger.info("Added education: %s", names)
    return {**done, "master_profile": updated, "current_question": gate(f"Added {names}. ", resume)}

def _save_certifications(resume: Dict[str, Any], fresh: List[Dict[str, Any]], done: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and merge only after the optional issuer/link follow-ups are complete."""
    candidate = dict(resume)
    candidate["certifications"] = list(candidate.get("certifications") or []) + fresh

    try:
        updated = Resume.model_validate(candidate).model_dump()
    except Exception as e:
        logger.warning("Certifications failed validation, discarding: %r", e)
        return {**done, "current_question": gate("That didn't fit the resume format. ", resume)}

    names = ", ".join(c["name"] for c in fresh)
    logger.info("Added certification(s): %s", names)
    return {**done, "master_profile": updated, "current_question": gate(f"Added {names}. ", resume)}

def _add_skills(resume: Dict[str, Any], answer: str, done: Dict[str, Any]) -> Dict[str, Any]:
    categories = [c.get("name", "") for c in (resume.get("skills") or []) if isinstance(c, dict)]

    try:
        parsed: ParsedSkills = get_openai_llm().with_structured_output(
            ParsedSkills, method="function_calling"
        ).invoke(PARSE_EXTRA_SKILLS.format(
            answer=answer, categories=", ".join(categories) or "(none yet)"
        ))
    except Exception as e:
        logger.error("Could not read the skills answer: %r", e)
        return {**done, "current_question": gate("I didn't catch that. ", resume)}

    placements = [
        ((s.keyword or "").strip(), (s.category or "").strip())
        for s in parsed.skills if (s.keyword or "").strip()
    ]
    if not placements:
        return {**done, "current_question": gate("I didn't catch a skill there. ", resume)}

    try:
        updated = Resume.model_validate(add_skills(resume, placements)).model_dump()
    except Exception as e:
        logger.warning("Skills failed validation, discarding: %r", e)
        return {**done, "current_question": gate("That didn't fit the resume format. ", resume)}

    names = ", ".join(k for k, _ in placements)
    logger.info("Added skill(s): %s", names)
    return {**done, "master_profile": updated, "current_question": gate(f"Added {names}. ", resume)}
