"""Deterministic 24-point resume-quality rubric."""

import re
from typing import Any, Dict, List, Tuple

from app.graphs.state import ResumeState

ACTION = re.compile(r"^(built|created|developed|designed|delivered|engineered|implemented|improved|increased|led|managed|optimized|reduced|shipped|launched|automated|architected)\b", re.I)
NUMBER = re.compile(r"\d")

def _item_score(values: List[bool]) -> int:
    return sum(bool(value) for value in values[:4])

def score_profile(profile: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]]]:
    """Return a transparent score out of 24 and its six four-point dimensions."""
    basics = profile.get("basics") or {}
    summary = (profile.get("summary") or {}).get("content", "").strip()
    experience = profile.get("experience") or []
    education = profile.get("education") or []
    projects = profile.get("projects") or []
    skills = profile.get("skills") or []
    bullets = [
        str(b).strip() for section in (experience, projects) for item in section
        for b in (item.get("highlights") or []) if str(b).strip()
    ]
    keywords = [str(k).strip() for category in skills for k in (category.get("keywords") or []) if str(k).strip()]

    dimensions = [
        ("Contact details", _item_score([
            bool(basics.get("name", "").strip()), bool(basics.get("email", "").strip()),
            bool(basics.get("phone", "").strip()), bool(basics.get("location", "").strip()),
        ]), "Add name, email, phone, and location."),

        ("Professional summary", _item_score([
            bool(summary), len(summary.split()) >= 20, 0 < len(summary.split()) <= 100,
            bool(re.search(r"\b(engineer|developer|designer|manager|analyst|specialist|student|intern)\b", summary, re.I)),
        ]), "Write a concise, role-focused summary of 20–100 words."),
        ("Experience completeness", _item_score([
            bool(experience), experience and all(item.get("company") and item.get("position") for item in experience),
            experience and all(item.get("start_date") and item.get("end_date") for item in experience), len(experience) >= 2,
        ]), "Include employer, title, dates, and relevant roles."),
        ("Impact evidence", _item_score([
            len(bullets) >= 2, len(bullets) >= 4,
            any(ACTION.search(bullet) for bullet in bullets), any(NUMBER.search(bullet) for bullet in bullets),
        ]), "Use action-led bullets and add truthful results or metrics where available."),
        ("Skills coverage", _item_score([
            bool(skills), len(skills) >= 2, len(keywords) >= 8,
            skills and all(category.get("name") and category.get("keywords") for category in skills),
        ]), "Group at least eight relevant skills under clear categories."),
        ("Education & projects", _item_score([
            bool(education), any(item.get("institution") and (item.get("area") or item.get("study_type")) for item in education),
            bool(projects), any(item.get("name") and (item.get("description") or item.get("highlights")) for item in projects),
        ]), "Add education and projects that demonstrate your work."),
    ]
    breakdown = [
        {"name": name, "score": score, "max_score": 4, "advice": advice}
        for name, score, advice in dimensions
    ]
    return sum(row["score"] for row in breakdown), breakdown

def score_resume_quality(state: ResumeState) -> Dict[str, Any]:
    generated = state.get("generated_resumes") or {}
    resume = generated.get("tailored") or state.get("master_profile") or {}
    profile = resume.model_dump() if hasattr(resume, "model_dump") else resume
    score, breakdown = score_profile(profile)
    return {"quality_score": score, "quality_feedback": breakdown}
