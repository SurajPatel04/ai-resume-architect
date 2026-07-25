import logging
import re
from datetime import datetime
from typing import Any, Dict, List
from app.graphs.apply import impact_key
from app.graphs.state import ResumeState

logger = logging.getLogger(__name__)

                                                                        
MAX_IMPACT_QUESTIONS = 3

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

_YEAR = re.compile(r"(?:19|20)\d{2}")


def _has_metric(text: str) -> bool:
                                                                                             
    return any(ch.isdigit() for ch in text or "")


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
    experience = resume.get("experience") or []
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

                                      
    total_fields = 5
    missing_count = 0
    basics = r.get("basics", {})
    for f in ["name", "email", "phone", "location", "linkedin"]:
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

    existing_queue = state.get("question_queue", [])
    if existing_queue:
        logger.info(f"question_queue has {len(existing_queue)} items remaining. Skipping gap analysis.")
        return {"completion": completion}
        
    logger.info("question_queue is empty. Recomputing gaps...")
    gaps = []
        
    skipped = state.get("skipped", [])
    if skipped is None:
        skipped = []

                                                                                       
                                                                                         
                                                                          
    seniority = infer_seniority(r)
    suppressed = set(SUPPRESSED_SECTIONS.get(seniority, ()))
    if suppressed:
        logger.info("Seniority %s — not asking about: %s", seniority, ", ".join(sorted(suppressed)))
    section_skips = set(skipped) | suppressed

            
    if "basics" not in section_skips:
        basics = r.get("basics", {})
        basics_missing = []
        for f in ["name", "email", "phone", "location", "linkedin"]:
            if not basics.get(f):
                basics_missing.append(f)
                
                                                
        basics_missing = [f for f in basics_missing if f"basics.{f}" not in skipped]
        
        if basics_missing:
            kind = "required" if any(f in basics_missing for f in ["name", "email", "phone"]) else "recommended"
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
                "missing_fields": ["company", "position", "highlights"],
                "is_gate": True,
                "reason": "No work experience listed."
            })
        else:
            for i, exp in enumerate(experience):
                exp_missing = []
                for f in ["company", "position", "highlights"]:
                    if not exp.get(f):
                        exp_missing.append(f)
                        
                exp_missing = [f for f in exp_missing if f"experience[{i}].{f}" not in skipped]
                
                if exp_missing:
                    kind = "required" if any(f in exp_missing for f in ["company", "position"]) else "recommended"
                    gaps.append({
                        "field": f"experience[{i}]",
                        "section": "experience",
                        "kind": kind,
                        "missing_fields": exp_missing,
                        "is_gate": False,
                        "reason": f"Experience entry {i+1} is missing: {', '.join(exp_missing)}."
                    })

               
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
            gaps.append({
                "field": "skills",
                "section": "skills",
                "kind": "required",
                "missing_fields": [],
                "is_gate": True,
                "reason": "No skills listed."
            })

              
    if "projects" not in section_skips:
        projects = r.get("projects", [])
        if not projects:
            gaps.append({
                "field": "projects[0]",
                "section": "projects",
                                                                                      
                "kind": "required" if seniority == "entry" else "recommended",
                "missing_fields": ["name", "highlights"],
                "is_gate": True,
                "reason": "No projects listed."
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

                                                                          
                                                                               
                                                                          
    impact_gaps = []
    for section_name in ("experience", "projects"):
        if section_name in skipped:
            continue
        for i, item in enumerate(r.get(section_name) or []):
            for j, hl in enumerate(item.get("highlights") or []):
                if _has_metric(hl) or impact_key(f"{section_name}[{i}]", j) in skipped:
                    continue
                impact_gaps.append({
                    "field": f"{section_name}[{i}]",
                    "section": "impact",
                    "kind": "impact",
                    "missing_fields": ["metric"],
                    "is_gate": False,
                    "bullet_index": j,
                    "weak_bullet": hl,
                    "reason": f'This bullet has no measurable result: "{hl}"',
                })
    impact_gaps = impact_gaps[:MAX_IMPACT_QUESTIONS]

                                                                                                                                                     
    filtered_gaps = [g for g in gaps if g["field"] not in skipped]

                                                           
    required_gaps = [g for g in filtered_gaps if g.get("kind") == "required"]
    recommended_gaps = [g for g in filtered_gaps if g.get("kind") == "recommended"]

    sorted_queue = required_gaps + impact_gaps + recommended_gaps

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

    def run(profile):
        return analyze_gaps({"master_profile": profile, "question_queue": [], "skipped": []})

    def sections(result):
        return {g["section"] for g in result["question_queue"]}

                                               
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
    order = {"required": 0, "impact": 1, "recommended": 2}
    ranks = [order[g["kind"]] for g in junior["question_queue"]]
    assert ranks == sorted(ranks), f"queue out of priority order: {ranks}"

                                                  
    blank = run({"experience": [], "projects": [], "education": [], "skills": [], "basics": {}})
    assert blank["seniority"] == "unknown"
    assert {"experience", "education", "skills", "projects"} <= sections(blank), sections(blank)

                                                    
    assert "skipped" not in exec_result, "suppression is per-run, not persisted"

                                                                                 
                                                                              
    exec_with_projects = run({
        "experience": [job("Director of Engineering", "2015", "2024")],
        "projects": [{"name": "Compiler", "highlights": ["Rewrote the parser"]}],
        "education": [], "skills": [], "basics": {},
    })
    impact = [g for g in exec_with_projects["question_queue"] if g["section"] == "impact"]
    assert any(g["field"] == "projects[0]" for g in impact), impact

    print("analyze_gaps ok")