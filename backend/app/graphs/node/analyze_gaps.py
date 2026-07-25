import logging
from typing import Any, Dict
from app.graphs.state import ResumeState

logger = logging.getLogger(__name__)

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

    # Calculate completion dynamically
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

    # Basics
    if "basics" not in skipped:
        basics = r.get("basics", {})
        basics_missing = []
        for f in ["name", "email", "phone", "location", "linkedin"]:
            if not basics.get(f):
                basics_missing.append(f)
                
        # Filter out fields individually skipped
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

    # Experience
    if "experience" not in skipped:
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

    # Education
    if "education" not in skipped:
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

    # Skills
    if "skills" not in skipped:
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

    # Projects
    if "projects" not in skipped:
        projects = r.get("projects", [])
        if not projects:
            gaps.append({
                "field": "projects[0]",
                "section": "projects",
                "kind": "recommended",
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

    # Filter out any gaps where the specific field was skipped (handled in-loop now, but we can do a final safety check if a whole group was skipped)
    filtered_gaps = [g for g in gaps if g["field"] not in skipped]

    # Sort gaps to prioritize 'required' over 'recommended'
    required_gaps = [g for g in filtered_gaps if g.get("kind") == "required"]
    recommended_gaps = [g for g in filtered_gaps if g.get("kind") == "recommended"]
    
    sorted_queue = required_gaps + recommended_gaps

    logger.info(f"Built question_queue with {len(sorted_queue)} gaps.")
    
    return {"question_queue": sorted_queue, "master_profile": r, "completion": completion}
