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
    """The "anything else for this section?" question, asked once its entries are listed.

    A gate, so "yes" opens the next empty entry and "no" marks the whole section skipped —
    which is what ends the loop. Always "recommended" so it sorts behind the holes in the
    entries that are already there: finish what's on the resume before adding to it.
    """
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
    """Span from earliest start to latest end.

    ponytail: ignores gaps and overlaps, and only reads 4-digit years out of free-text
    dates. Good enough to bucket someone; not a tenure calculation.
    """
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
    """Bucket the candidate so the interview can skip questions that don't apply.

    Returns "unknown" until there's at least one job to judge by — guessing from an
    empty profile would suppress the very questions that fill it in.
    """
                                                                                     
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
    """
    Examines the current master_profile and identifies missing or incomplete fields.
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

if __name__ == "__main__":
    now = datetime.now().year

    def job(position="Engineer", start="", end="", highlights=None):
        return {"company": "Acme", "position": position, "start_date": start,
                "end_date": end, "highlights": highlights or ["Did a thing"]}

    def run(profile, **state):
        return analyze_gaps({"master_profile": profile, "question_queue": [], "skipped": [], **state})

    def sections(result):
        return {g["section"] for g in result["question_queue"]}

    def order_of(result):
        return [g["section"] for g in result["question_queue"]]

    def visits(result):
        """Sections in the order they are entered, consecutive runs collapsed to one."""
        asked = order_of(result)
        return [s for i, s in enumerate(asked) if i == 0 or s != asked[i - 1]]

    EMPTY = {"experience": [], "projects": [], "education": [], "skills": [], "basics": {}}

    assert _years_of_experience([job(start="2000", end="2020")]) == 20
    assert _years_of_experience([job(start="2020", end="Present")]) == now - 2020
    assert _years_of_experience([job(start="2018", end="2021"), job(start="2021", end="2024")]) == 6
    assert _years_of_experience([job()]) == 0, "undated experience shouldn't invent tenure"

    assert infer_seniority({"experience": []}) == "unknown", "never guess from an empty profile"
    assert infer_seniority({"experience": [job("Head of Marketing", "2022", "2024")]}) == "executive"
    assert infer_seniority({"experience": [job("VP Engineering", "2023", "2024")]}) == "executive"
    assert infer_seniority({"experience": [job(start="2000", end="2020")]}) == "executive"
    assert infer_seniority({"experience": [job(start="2016", end="2024")]}) == "senior"
    assert infer_seniority({"experience": [job(start="2021", end="2024")]}) == "mid"
    assert infer_seniority({"experience": [job(start="2024", end="2024")]}) == "entry"

    exec_result = run({"experience": [job("Director of Engineering", "2015", "2024")],
                       "projects": [], "education": [], "skills": [], "basics": {}})
    assert exec_result["seniority"] == "executive"
    assert "projects" not in sections(exec_result), sections(exec_result)

    junior = run({"experience": [job(start="2024", end="2024")],
                  "projects": [], "education": [], "skills": [], "basics": {}})
    assert junior["seniority"] == "entry"
    projects_gap = next(g for g in junior["question_queue"] if g["section"] == "projects")
    assert projects_gap["kind"] == "required", projects_gap

    part_way = run(
        {"basics": {"name": "S", "email": "s@x.com", "phone": "1"},
         "education": [{"institution": "Amity University", "area": ""}],
         "projects": [{"name": "Manim generator", "highlights": []}],
         "experience": [], "skills": []},
        career_level="fresher",
    )
    assert visits(part_way) == ["basics", "education", "projects", "target_role", "skills"],\
        order_of(part_way)

    two_jobs = run({**EMPTY, "experience": [
        {"company": "Acme", "position": "Engineer", "highlights": []},
        {"company": "", "position": "", "highlights": ["Did a thing"]},
    ]}, career_level="experienced")
    jobs_asked = [g["field"] for g in two_jobs["question_queue"] if g["section"] == "experience"]
    assert jobs_asked == ["experience[0]", "experience[1]", "experience[2]"], jobs_asked

    for result in (part_way, two_jobs, junior):
        seen = visits(result)
        assert len(seen) == len(set(seen)), f"section revisited: {order_of(result)}"

    one_degree = run({**EMPTY, "education": [{"institution": "Amity University", "area": "MCA"}]},
                     career_level="fresher")
    assert "education" not in sections(one_degree), one_degree["question_queue"]
    first_project = next(g for g in one_degree["question_queue"] if g["section"] == "projects")
    assert not first_project["is_gate"] and first_project["field"] == "projects[0]", first_project

    complete_job = job(start="Dec 2025", end="Present", highlights=["Built APIs"])
    stale = {"field": "experience[0]", "section": "experience", "is_gate": False,
             "missing_fields": ["start_date", "end_date", "highlights"]}
    assert is_resolved_gap({"experience": [complete_job]}, stale)

    assert "education" not in sections(run(
        {**EMPTY, "education": [{"institution": "Amity University", "area": "MCA"}]},
        career_level="fresher", skipped=["education"]))

    blank = run(EMPTY)
    assert blank["seniority"] == "unknown"
    assert {"experience", "education", "skills", "projects"} <= sections(blank), sections(blank)

    assert order_of(blank)[0] == "career_level", order_of(blank)

    fresher = run(EMPTY, career_level="fresher")
    assert "career_level" not in sections(fresher)
    assert "experience" not in sections(fresher), sections(fresher)
    assert order_of(fresher) == ["basics", "education", "projects", "target_role", "skills"], order_of(fresher)
    assert next(g for g in fresher["question_queue"] if g["section"] == "projects")["kind"] == "required"

    intern = run(EMPTY, career_level="internship")
    assert order_of(intern) == ["basics", "education", "experience", "projects", "target_role", "skills"]

    working = run(EMPTY, career_level="experienced")
    assert order_of(working) == ["basics", "experience", "education", "target_role", "skills", "projects"]
    assert next(g for g in working["question_queue"] if g["section"] == "projects")["kind"] == "recommended"

    for result in (fresher, intern, working, blank):
        sections_asked = order_of(result)
        assert sections_asked.index("target_role") < sections_asked.index("skills"), sections_asked

    assert "target_role" not in sections(run(EMPTY, target_role="Backend Engineer"))
    assert "target_role" not in sections(analyze_gaps(
        {"master_profile": EMPTY, "question_queue": [], "skipped": ["target_role"]}))
    assert "career_level" not in sections(analyze_gaps(
        {"master_profile": EMPTY, "question_queue": [], "skipped": ["career_level"]}))

    listed = run({**EMPTY, "skills": [{"name": "Languages", "keywords": ["Python"]}]})
    assert "target_role" not in sections(listed) and "skills" not in sections(listed)

    imported = run({**EMPTY, "experience": [job(start="2019", end="Present")]})
    assert "career_level" not in sections(imported), sections(imported)

    assert "skipped" not in exec_result, "suppression is per-run, not persisted"

    links = run({"basics": {"name": "S", "email": "s@x.com", "phone": "1", "location": "Delhi"}},
                career_level="fresher")
    basics_gap = next(g for g in links["question_queue"] if g["section"] == "basics")
    assert basics_gap["missing_fields"] == ["linkedin", "github", "website"], basics_gap
    assert basics_gap["kind"] == "recommended", "a portfolio link is not worth blocking on"
    assert sum(1 for g in links["question_queue"] if g["section"] == "basics") == 1,\
        "three links must not become three questions"

    one_left = analyze_gaps({"master_profile": {"basics": {"name": "S", "email": "e", "phone": "1",
                                                           "location": "D", "github": "gh"}},
                             "question_queue": [], "skipped": ["basics.website"]})
    assert next(g for g in one_left["question_queue"] if g["section"] == "basics")["missing_fields"]\
        == ["linkedin"], "a skipped link must not come back"

    written = run({
        "basics": {"name": "S", "email": "s@x.com", "phone": "1", "location": "Delhi",
                   "linkedin": "in/s", "github": "gh/s", "website": "s.dev"},
        "experience": [{**job(start="2020", end="2024"), "highlights": ["Did the thing"]}],
        "education": [{"institution": "IIT", "area": "CS"}],
        "skills": [{"name": "Languages", "keywords": ["Python"]}],
        "projects": [{"name": "Parser", "highlights": ["Wrote it"]}],
    })
                                                                                        
    assert order_of(written) == ["experience", "projects"], order_of(written)
    assert all(g.get("is_more") for g in written["question_queue"]), written["question_queue"]
    assert visits(written) == list(dict.fromkeys(order_of(written))), "still one section at a time"

    settled = analyze_gaps({"master_profile": written["master_profile"], "question_queue": [],
                            "skipped": ["experience", "education", "projects"]})
    assert settled["question_queue"] == [], settled["question_queue"]

    print("analyze_gaps ok")
