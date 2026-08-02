import logging
import re
from datetime import datetime
from typing import Any, Dict, List
from app.graphs.state import ResumeState

logger = logging.getLogger(__name__)

EXEC_TITLES = (
    "chief", "ceo", "cto", "coo", "cfo", "cmo", "vp", "vice president", "president",
    "head of", "director", "partner", "founder", "principal",
)

SUPPRESSED_SECTIONS = {

    "executive": ("projects",),
    "senior": (),
    "mid": (),
    "entry": (),
    "unknown": (),
}

SECTION_ORDER = {
    "fresher": ("career_level", "basics", "education", "projects", "target_role", "skills"),
    "internship": ("career_level", "basics", "education", "experience", "projects", "target_role", "skills"),
    "experienced": ("career_level", "basics", "experience", "education", "target_role", "skills", "projects"),
}

DEFAULT_ORDER = SECTION_ORDER["experienced"]

CAREER_SUPPRESSED = {"fresher": ("experience",)}

KIND_RANK = {"required": 0, "recommended": 1}

MORE_FIELDS = {
    "experience": ["company", "position", "start_date", "end_date", "highlights"],
    "education": ["institution", "area"],
    "projects": ["name", "highlights"],
}

def more_gate(section: str, count: int) -> Dict[str, Any]:
    """The "anything else for this section?" question, asked once its entries are listed."""
    return {
        "field": f"{section}[{count}]",
        "section": section,
        "kind": "recommended",
        "missing_fields": MORE_FIELDS[section],
        "is_gate": True,

        "is_more": True,
        "reason": f"{count} {section} entr{'y' if count == 1 else 'ies'} recorded; there may be more.",
    }

def is_skipped_gap(gap: Dict[str, Any], skipped: List[str]) -> bool:
    """Whether every part of a queued question has already been declined."""
    section = gap.get("section")
    field = gap.get("field")
    if section in skipped or field in skipped:
        return True
    missing = gap.get("missing_fields") or []
    return bool(missing) and all(f"{field}.{name}" in skipped for name in missing)

def is_resolved_gap(resume: Dict[str, Any], gap: Dict[str, Any]) -> bool:
    """Whether a queued question is stale because its requested fields now exist."""
    if gap.get("is_more") or gap.get("is_gate"):
        return False
    fields = gap.get("missing_fields") or []
    if not fields:
        return False
    field = gap.get("field") or ""
    section, _, index = field.partition("[")
    value: Any = resume.get(section) or {}
    if index:
        if not isinstance(value, list):
            return False
        item_index = int(index.rstrip("]") or 0)
        value = value[item_index] if item_index < len(value) else {}
    return isinstance(value, dict) and all(bool(value.get(name)) for name in fields)

BASIC_FIELDS = ("name", "email", "phone", "location", "linkedin", "github", "website")

REQUIRED_BASICS = ("name", "email", "phone")

_YEAR = re.compile(r"(?:19|20)\d{2}")

def _years_of_experience(experience: List[Dict[str, Any]]) -> int:
    """Span from earliest start to latest end."""
    starts, ends = [], []
    this_year = datetime.now().year
    for e in experience:
        start = _YEAR.search(e.get("start_date") or "")
        if start:
            starts.append(int(start.group()))
        end_text = (e.get("end_date") or "").lower()
        if "present" in end_text or "current" in end_text:
            ends.append(this_year)
        else:
            end = _YEAR.search(end_text)
            if end:
                ends.append(int(end.group()))
    if not starts:
        return 0
    return max(max(ends, default=this_year) - min(starts), 0)

def infer_seniority(resume: Dict[str, Any]) -> str:
    """Bucket the candidate so the interview can skip questions that don't apply."""

    experience = [e for e in (resume.get("experience") or []) if any(e.values())]
    if not experience:
        return "unknown"

    titles = " ".join((e.get("position") or "") for e in experience).lower()
    if any(t in titles for t in EXEC_TITLES):
        return "executive"

    years = _years_of_experience(experience)
    if years >= 12:
        return "executive"
    if years >= 6:
        return "senior"
    if years >= 2:
        return "mid"
    return "entry"

def analyze_gaps(state: ResumeState) -> Dict[str, Any]:
    """Examines the current master_profile and identifies missing or incomplete fields.
    Produces an ordered question_queue if one doesn't exist.
    """
    resume = state.get("master_profile", {})
    if hasattr(resume, "model_dump"):
        r = resume.model_dump()
    else:
        r = resume

    total_fields = len(BASIC_FIELDS)
    missing_count = 0
    basics = r.get("basics", {})
    for f in BASIC_FIELDS:
        if not basics.get(f): missing_count += 1

    experience = r.get("experience", [])
    if not experience:
        total_fields += 1
        missing_count += 1
    else:
        total_fields += 3 * len(experience)
        for exp in experience:
            for f in ["company", "position", "highlights"]:
                if not exp.get(f): missing_count += 1

    education = r.get("education", [])
    if not education:
        total_fields += 1
        missing_count += 1
    else:
        total_fields += 2 * len(education)
        for edu in education:
            for f in ["institution", "area"]:
                if not edu.get(f): missing_count += 1

    skills = r.get("skills", [])
    total_fields += 1
    if not skills: missing_count += 1

    projects = r.get("projects", [])
    if not projects:
        total_fields += 1
        missing_count += 1
    else:
        total_fields += 2 * len(projects)
        for proj in projects:
            for f in ["name", "highlights"]:
                if not proj.get(f): missing_count += 1

    completion = int(((total_fields - missing_count) / total_fields) * 100) if total_fields > 0 else 0
    logger.info(f"Calculated profile completion: {completion}%")

    skipped = state.get("skipped") or []
    existing_queue = [
        gap for gap in (state.get("question_queue") or [])
        if not is_skipped_gap(gap, skipped) and not is_resolved_gap(r, gap)
    ]
    if existing_queue:
        logger.info("question_queue has %d unskipped item(s) remaining. Skipping gap analysis.", len(existing_queue))
        return {"completion": completion, "question_queue": existing_queue}

    logger.info("question_queue is empty. Recomputing gaps...")
    gaps = []

    seniority = infer_seniority(r)
    career_level = state.get("career_level")
    suppressed = set(SUPPRESSED_SECTIONS.get(seniority, ())) | set(CAREER_SUPPRESSED.get(career_level, ()))
    if suppressed:
        logger.info("Seniority %s / %s — not asking about: %s",
                    seniority, career_level or "unclassified", ", ".join(sorted(suppressed)))
    section_skips = set(skipped) | suppressed

    if not career_level and not experience and "career_level" not in skipped:
        gaps.append({
            "field": "career_level",
            "section": "career_level",
            "kind": "required",
            "missing_fields": [],
            "is_gate": True,
            "reason": "Don't know yet whether they're a fresher, an intern, or working.",
        })

    if "basics" not in section_skips:
        basics = r.get("basics", {})
        basics_missing = []
        for f in BASIC_FIELDS:
            if not basics.get(f):
                basics_missing.append(f)

        basics_missing = [f for f in basics_missing if f"basics.{f}" not in skipped]

        if basics_missing:
            kind = "required" if any(f in basics_missing for f in REQUIRED_BASICS) else "recommended"
            gaps.append({
                "field": "basics",
                "section": "basics",
                "kind": kind,
                "missing_fields": basics_missing,
                "is_gate": False,
                "reason": f"Missing basic info: {', '.join(basics_missing)}."
            })

    if "experience" not in section_skips:
        experience = r.get("experience", [])
        if not experience:
            gaps.append({
                "field": "experience[0]",
                "section": "experience",
                "kind": "required",
                "missing_fields": ["company", "position", "start_date", "end_date", "highlights"],
                "is_gate": True,
                "reason": "No work experience listed."
            })
        else:
            for i, exp in enumerate(experience):
                exp_missing = []
                for f in ["company", "position", "start_date", "end_date", "highlights"]:
                    if not exp.get(f):
                        exp_missing.append(f)

                exp_missing = [f for f in exp_missing if f"experience[{i}].{f}" not in skipped]

                if exp_missing:
                    kind = "required" if any(
                        f in exp_missing for f in ["company", "position", "start_date", "end_date"]
                    ) else "recommended"
                    gaps.append({
                        "field": f"experience[{i}]",
                        "section": "experience",
                        "kind": kind,
                        "missing_fields": exp_missing,
                        "is_gate": False,
                        "reason": f"Experience entry {i+1} is missing: {', '.join(exp_missing)}."
                    })
            gaps.append(more_gate("experience", len(experience)))

    if "education" not in section_skips:
        education = r.get("education", [])
        if not education:
            gaps.append({
                "field": "education[0]",
                "section": "education",
                "kind": "required",
                "missing_fields": ["institution", "area"],
                "is_gate": True,
                "reason": "No education listed."
            })
        else:
            for i, edu in enumerate(education):
                edu_missing = []
                for f in ["institution", "area"]:
                    if not edu.get(f):
                        edu_missing.append(f)

                edu_missing = [f for f in edu_missing if f"education[{i}].{f}" not in skipped]

                if edu_missing:
                    kind = "required" if "institution" in edu_missing else "recommended"
                    gaps.append({
                        "field": f"education[{i}]",
                        "section": "education",
                        "kind": kind,
                        "missing_fields": edu_missing,
                        "is_gate": False,
                        "reason": f"Education entry {i+1} is missing: {', '.join(edu_missing)}."
                    })

    if "skills" not in section_skips:
        skills = r.get("skills", [])
        if not skills:

            if not state.get("target_role") and "target_role" not in skipped:
                gaps.append({
                    "field": "target_role",
                    "section": "target_role",
                    "kind": "required",
                    "missing_fields": [],
                    "is_gate": True,
                    "reason": "Skills should be asked for a specific role, not in general.",
                })

            gaps.append({
                "field": "skills",
                "section": "skills",
                "kind": "required",

                "missing_fields": ["skills"],
                "is_gate": True,
                "reason": "No skills listed."
            })

    if "projects" not in section_skips:
        projects = r.get("projects", [])
        if not projects:
            gaps.append({
                "field": "projects[0]",
                "section": "projects",

                "kind": "required" if career_level in ("fresher", "internship")
                        or seniority == "entry" else "recommended",
                "missing_fields": ["name", "highlights"],

                "is_gate": False,
                "skip_section_if_empty": True,
                "reason": "No projects listed; ask for the first project directly."
            })
        else:
            for i, proj in enumerate(projects):
                proj_missing = []
                for f in ["name", "highlights"]:
                    if not proj.get(f):
                        proj_missing.append(f)

                proj_missing = [f for f in proj_missing if f"projects[{i}].{f}" not in skipped]

                if proj_missing:
                    gaps.append({
                        "field": f"projects[{i}]",
                        "section": "projects",
                        "kind": "recommended",
                        "missing_fields": proj_missing,
                        "is_gate": False,
                        "reason": f"Project entry {i+1} is missing: {', '.join(proj_missing)}."
                    })
            gaps.append(more_gate("projects", len(projects)))

    filtered_gaps = [g for g in gaps if g["field"] not in skipped]

    order = SECTION_ORDER.get(career_level, DEFAULT_ORDER)

    def rank(gap: Dict[str, Any]) -> tuple:
        section = gap.get("section", "")
        return (
            order.index(section) if section in order else len(order),
            KIND_RANK.get(gap.get("kind"), 1),
        )

    sorted_queue = sorted(filtered_gaps, key=rank)

    logger.info(f"Built question_queue with {len(sorted_queue)} gaps.")

    return {
        "question_queue": sorted_queue,
        "master_profile": r,
        "completion": completion,
        "seniority": seniority,
    }
