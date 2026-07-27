"""The last thing asked before the resume is built: anything else to add?

analyze_gaps only queues fields that are empty in a section the resume already has, and
review_quality only looks at bullets that exist. Neither can raise a certification the
user never wrote down, or a skill they forgot — nothing empty ever points at them.

One chip-driven question rather than a checklist. "No, I'm done" is always on offer, and
answering either branch comes straight back here so a second addition costs one more tap
rather than another interrogation.
"""

import logging
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.graphs.node.skill_gap import ClaimedSkill, add_skills
from app.graphs.state import Certification, Resume, ResumeState
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

ISSUER_BY_CHIP = {
    AWS_ISSUER_CHIP: "Amazon Web Services (AWS)",
    GCP_ISSUER_CHIP: "Google Cloud",
    AZURE_ISSUER_CHIP: "Microsoft Azure",
}

class ParsedCertifications(BaseModel):
    certifications: List[Certification] = Field(
        default_factory=list,
        description="One entry per certification, licence or award the user named. Copy what they "
        "wrote — never invent an issuer, date, or credential URL they did not give.",
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

def gate(prefix: str = "") -> Dict[str, Any]:
    """The one question. `prefix` acknowledges what was just added."""
    return _question(
        f"{prefix}Anything else to add before I build your resume?",
        step="gate",
        ui="chips",
        options=[CERT_CHIP, SKILLS_CHIP, DONE_CHIP],
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
        ).invoke(f"""
        Suggest up to five likely issuing organizations for these certification names: {names or "unspecified certification"}.
        They are selectable suggestions only, not facts about the candidate. Use official issuer names,
        not training providers, and return no generic companies unrelated to the credential.
        """)
        suggestions.extend(result.issuers)
    except Exception as e:
        logger.warning("Could not generate certification issuer suggestions: %r", e)

    unique: List[str] = []
    seen = set()
    for issuer in suggestions:
        label = (issuer or "").strip()
        if label and label.casefold() not in seen:
            unique.append(label)
            seen.add(label.casefold())
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
        ).invoke(f"""
        Suggest up to 8 concrete technical skills relevant to {context}.
        Already listed skills: {", ".join(sorted(existing)) or "none"}

        Return only short languages, frameworks, tools, cloud services, or protocols that
        are NOT already listed. These are suggestions only: never claim the candidate has
        them, and do not include soft skills or sentences.
        """)
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

    if not (answer and pending.get("section") == GATE_SECTION):
                                                                                   
        logger.info("Offering the final additions.")
        return {"extras_offered": True, "current_question": gate()}

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
        if answer == SKILLS_CHIP:
            resume = state.get("master_profile", {})
            if hasattr(resume, "model_dump"):
                resume = resume.model_dump()
            suggestions = suggested_extra_skills(resume, state.get("target_role") or "")
            return {**done, "current_question": _question(
                "Tap a suggested skill you genuinely have, or type additional skills separated "
                "by commas. I will add only the skills you confirm.",
                step="skills",
                ui="chips",
                options=suggestions + [DONE_CHIP],
            )}
                                                                                         
        return {**done, "current_question": gate()}

    resume = state.get("master_profile", {})
    if hasattr(resume, "model_dump"):
        resume = resume.model_dump()

    if step == "certifications":
        return _add_certifications(resume, answer, done)

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
        ).invoke(f"""
    The user was asked which certifications, licences or awards they hold.

    THEIR REPLY: "{answer}"

    Pull out one entry per credential they named. Leave issuer, date, and credential URL
    empty when they did not say them — a resume that states details they never mentioned
    is a fabrication and they will be asked about them. Return nothing if they named no
    credential.
    """)
    except Exception as e:
        logger.error("Could not read the certifications answer: %r", e)
        return {**done, "current_question": gate("I didn't catch that. ")}

    fresh = keep_certifications(parsed.certifications)
    if not fresh:
        return {**done, "current_question": gate("I didn't catch a certification there. ")}

    if any(not cert.get("issuer") for cert in fresh):
        return {**done, "current_question": _issuer_question(fresh)}

    if any(not cert.get("url") for cert in fresh):
        return {**done, "current_question": _credential_link_question(fresh)}

    return _save_certifications(resume, fresh, done)

def _save_certifications(resume: Dict[str, Any], fresh: List[Dict[str, Any]], done: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and merge only after the optional issuer/link follow-ups are complete."""
    candidate = dict(resume)
    candidate["certifications"] = list(candidate.get("certifications") or []) + fresh

    try:
        updated = Resume.model_validate(candidate).model_dump()
    except Exception as e:
        logger.warning("Certifications failed validation, discarding: %r", e)
        return {**done, "current_question": gate("That didn't fit the resume format. ")}

    names = ", ".join(c["name"] for c in fresh)
    logger.info("Added certification(s): %s", names)
    return {**done, "master_profile": updated, "current_question": gate(f"Added {names}. ")}

def _add_skills(resume: Dict[str, Any], answer: str, done: Dict[str, Any]) -> Dict[str, Any]:
    categories = [c.get("name", "") for c in (resume.get("skills") or []) if isinstance(c, dict)]

    try:
        parsed: ParsedSkills = get_openai_llm().with_structured_output(
            ParsedSkills, method="function_calling"
        ).invoke(f"""
    The user was asked which extra skills to add to their resume.

    THEIR REPLY: "{answer}"

    Pull out one entry per skill they named, exactly as they wrote it. File each under one
    of their existing categories: {", ".join(categories) or "(none yet)"}. Only name a new
    category when none of those fit. Add nothing they did not say.
    """)
    except Exception as e:
        logger.error("Could not read the skills answer: %r", e)
        return {**done, "current_question": gate("I didn't catch that. ")}

    placements = [
        ((s.keyword or "").strip(), (s.category or "").strip())
        for s in parsed.skills if (s.keyword or "").strip()
    ]
    if not placements:
        return {**done, "current_question": gate("I didn't catch a skill there. ")}

    try:
        updated = Resume.model_validate(add_skills(resume, placements)).model_dump()
    except Exception as e:
        logger.warning("Skills failed validation, discarding: %r", e)
        return {**done, "current_question": gate("That didn't fit the resume format. ")}

    names = ", ".join(k for k, _ in placements)
    logger.info("Added skill(s): %s", names)
    return {**done, "master_profile": updated, "current_question": gate(f"Added {names}. ")}

if __name__ == "__main__":
                                                                               
    opened = add_extras({})
    assert opened["extras_offered"] is True
    q = opened["current_question"]
    assert q["section"] == GATE_SECTION and q["step"] == "gate"
    assert q["options"] == [CERT_CHIP, SKILLS_CHIP, DONE_CHIP]
    assert len(q["question_text"].split()) < 60, "mobile-first: keep it short"

    def reply(question, answer, profile=None):
        return add_extras({
            "current_question": question,
            "latest_answer": answer,
            "master_profile": profile or {},
        })

    for step_q in (q, _question("x", "certifications"), _question("x", "skills"),
                   _question("x", "certification_issuer"), _question("x", "certification_link")):
        assert DONE_CHIP in step_q["options"], step_q["step"]
        assert reply(step_q, DONE_CHIP) == {"latest_answer": None, "current_question": None}

    assert reply(q, CERT_CHIP)["current_question"]["step"] == "certifications"
    assert reply(q, SKILLS_CHIP)["current_question"]["step"] == "skills"

    assert reply(q, "hmm")["current_question"]["step"] == "gate"

    assert keep_certifications([Certification(name="", issuer="Amazon")]) == []
    assert keep_certifications([Certification(name="  ")]) == []
    kept = keep_certifications([Certification(name="AWS SAA", issuer="Amazon", date="2025")])
    assert kept == [{"name": "AWS SAA", "issuer": "Amazon", "date": "2025", "url": ""}]

    assert gate("Added AWS SAA. ")["question_text"].startswith("Added AWS SAA. ")
    assert gate()["step"] == "gate"

    print("add_extras ok")
