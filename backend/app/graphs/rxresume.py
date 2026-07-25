"""Reactive Resume schema v5.0.0 adapter.

The interior of this app keeps bullets as `List[str]` and dates as start/end pairs
because analyze_gaps, apply_extraction and enhance_resume all operate per-bullet.
RxResume stores bullets as one HTML string and dates as one `period` string. Rather
than degrade the working schema, this module translates at the boundary.

Spec: https://rxresu.me/schema.json  (top-level required: picture, basics, summary,
sections, customSections, metadata)
"""

import re
import uuid
from html import escape, unescape
from typing import Any, Dict, List

from app.graphs.state import (
    Basics,
    Education,
    Experience,
    Project,
    Resume,
    SkillCategory,
    Summary,
)

SCHEMA_URL = "https://rxresu.me/schema.json"
SCHEMA_VERSION = "5.0.0"

                                                                
SECTION_TITLES = {
    "profiles": "Profiles",
    "experience": "Experience",
    "education": "Education",
    "projects": "Projects",
    "skills": "Skills",
    "languages": "Languages",
    "interests": "Interests",
    "awards": "Awards",
    "certifications": "Certifications",
    "publications": "Publications",
    "volunteer": "Volunteering",
    "references": "References",
}

                                                           
MAPPED_SECTIONS = ("profiles", "experience", "education", "projects", "skills")

_ID_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")                      

_TAGS = re.compile(r"<[^>]+>")
_LI = re.compile(r"<li[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
_BLOCK = re.compile(r"</p>|<br\s*/?>", re.IGNORECASE)
_PERIOD_SPLIT = re.compile(r"\s*[–—-]\s*|\s+to\s+", re.IGNORECASE)


def _stable_id(*parts: str) -> str:
    """Deterministic item id, so re-exporting the same resume doesn't churn ids."""
    return str(uuid.uuid5(_ID_NS, "|".join(parts)))


def _item_link(url: str = "") -> Dict[str, Any]:
    """Section-item website object. Note basics.website omits inlineLink."""
    return {"url": url or "", "label": "", "inlineLink": False}


def _strip_html(text: str) -> str:
    return unescape(_TAGS.sub("", text or "")).strip()


def bullets_to_html(items: List[str]) -> str:
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{escape(i)}</li>" for i in items if i) + "</ul>"


def html_to_bullets(html: str) -> List[str]:
    if not html:
        return []
    chunks = _LI.findall(html)
    if not chunks:
                                                                                     
        chunks = _BLOCK.split(html)
    return [b for b in (_strip_html(c) for c in chunks) if b]


def join_period(start: str, end: str) -> str:
    start, end = (start or "").strip(), (end or "").strip()
    if start and end:
        return f"{start} - {end}"
    return start or end


def split_period(period: str) -> tuple[str, str]:
    period = (period or "").strip()
    if not period:
        return "", ""
    parts = _PERIOD_SPLIT.split(period, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return period, ""


def _section(key: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "title": SECTION_TITLES[key],
        "columns": 1,                                                                
        "hidden": not items,
        "items": items,
    }


def _profile_item(network: str, value: str, base_url: str, icon: str) -> Dict[str, Any]:
    """linkedin/github are stored as 'URL or username', so accept either."""
    if value.startswith(("http://", "https://")):
        url = value
        username = value.rstrip("/").rsplit("/", 1)[-1]
    else:
        username = value.lstrip("@")
        url = base_url + username
    return {
        "id": _stable_id("profile", network, username),
        "hidden": False,
        "icon": icon,
        "iconColor": "",
        "network": network,
        "username": username,
        "website": _item_link(url),
    }


def _metadata() -> Dict[str, Any]:
    """Single-column, full-width layout — the ATS-safe arrangement the brief asks for."""
    return {
        "template": "onyx",
        "layout": {
            "sidebarWidth": 35,
            "pages": [{
                "fullWidth": True,
                "main": ["summary", "experience", "education", "projects", "skills", "profiles"],
                "sidebar": [],
            }],
        },
        "page": {
            "gapX": 12, "gapY": 12, "marginX": 48, "marginY": 48,
            "format": "a4", "locale": "en-US", "hideIcons": False,
        },
        "design": {
                                                                                 
            "level": {"icon": "", "type": "hidden"},
            "colors": {
                "primary": "rgba(37, 99, 235, 1)",
                "text": "rgba(0, 0, 0, 1)",
                "background": "rgba(255, 255, 255, 1)",
            },
        },
        "typography": {
            "body": {"fontFamily": "Inter", "fontWeights": ["400"], "fontSize": 11, "lineHeight": 1.5},
            "heading": {"fontFamily": "Inter", "fontWeights": ["600"], "fontSize": 14, "lineHeight": 1.3},
        },
        "notes": "",
    }


def _picture() -> Dict[str, Any]:
    return {
        "hidden": True, "url": "", "size": 64, "rotation": 0, "aspectRatio": 1.0,
        "borderRadius": 0, "borderColor": "rgba(0, 0, 0, 1)", "borderWidth": 0,
        "shadowColor": "rgba(0, 0, 0, 1)", "shadowWidth": 0,
    }


def to_rxresume(resume: Resume | Dict[str, Any]) -> Dict[str, Any]:
    """Our profile -> a document that validates against rxresu.me/schema.json."""
    r = resume.model_dump() if hasattr(resume, "model_dump") else dict(resume or {})
    basics = r.get("basics") or {}

    experience = r.get("experience") or []
    profiles = []
    if basics.get("linkedin"):
        profiles.append(_profile_item("LinkedIn", basics["linkedin"], "https://linkedin.com/in/", "linkedin-logo"))
    if basics.get("github"):
        profiles.append(_profile_item("GitHub", basics["github"], "https://github.com/", "github-logo"))

    items = {
        "profiles": profiles,
        "experience": [{
            "id": _stable_id("exp", e.get("company", ""), e.get("position", ""), str(i)),
            "hidden": False,
            "company": e.get("company", ""),
            "position": e.get("position", ""),
            "location": e.get("location", ""),
            "period": join_period(e.get("start_date", ""), e.get("end_date", "")),
            "website": _item_link(),
            "description": bullets_to_html(e.get("highlights") or []),
            "roles": [],
        } for i, e in enumerate(experience)],
        "education": [{
            "id": _stable_id("edu", e.get("institution", ""), str(i)),
            "hidden": False,
            "school": e.get("institution", ""),
            "degree": e.get("study_type", ""),
            "area": e.get("area", ""),
            "grade": e.get("gpa", ""),
            "location": "",
            "period": join_period(e.get("start_date", ""), e.get("end_date", "")),
            "website": _item_link(),
            "description": "",
        } for i, e in enumerate(r.get("education") or [])],
        "projects": [{
            "id": _stable_id("proj", p.get("name", ""), str(i)),
            "hidden": False,
            "name": p.get("name", ""),
            "period": "",
            "website": _item_link(p.get("url", "")),
                                                                            
            "description": (f"<p>{escape(p['description'])}</p>" if p.get("description") else "")
                           + bullets_to_html(p.get("highlights") or []),
        } for i, p in enumerate(r.get("projects") or [])],
                                                                                      
        "skills": [{
            "id": _stable_id("skill", s.get("name", ""), str(i)),
            "hidden": False,
            "icon": "",
            "iconColor": "",
            "name": s.get("name", ""),
            "proficiency": "",
            "level": 0,
            "keywords": s.get("keywords") or [],
        } for i, s in enumerate(r.get("skills") or [])],
    }

    summary_text = (r.get("summary") or {}).get("content", "")

    return {
        "$schema": SCHEMA_URL,
        "version": SCHEMA_VERSION,
        "picture": _picture(),
        "basics": {
            "name": basics.get("name", ""),
                                                                                    
            "headline": experience[0].get("position", "") if experience else "",
            "email": basics.get("email", ""),
            "phone": basics.get("phone", ""),
            "location": basics.get("location", ""),
            "website": {"url": basics.get("website", ""), "label": ""},
            "customFields": [],
        },
        "summary": {
            "title": "Summary",
            "columns": 1,
            "hidden": not summary_text,
            "content": f"<p>{escape(summary_text)}</p>" if summary_text else "",
        },
        "sections": {key: _section(key, items.get(key, [])) for key in SECTION_TITLES},
        "customSections": [],
        "metadata": _metadata(),
    }


def looks_like_rxresume(doc: Any) -> bool:
    return isinstance(doc, dict) and isinstance(doc.get("sections"), dict) and "basics" in doc


def from_rxresume(doc: Dict[str, Any]) -> Resume:
    """An RxResume document -> our profile. Unmapped sections are dropped."""
    basics = doc.get("basics") or {}
    sections = doc.get("sections") or {}

    def items(key: str) -> List[Dict[str, Any]]:
        return (sections.get(key) or {}).get("items") or []

    linkedin = github = ""
    for p in items("profiles"):
        network = (p.get("network") or "").lower()
        handle = (p.get("website") or {}).get("url") or p.get("username", "")
        if network == "linkedin":
            linkedin = handle
        elif network == "github":
            github = handle

    website = basics.get("website")
    if isinstance(website, dict):
        website = website.get("url", "")

    experience = []
    for e in items("experience"):
        start, end = split_period(e.get("period", ""))
        experience.append(Experience(
            company=e.get("company", ""),
            position=e.get("position", ""),
            location=e.get("location", ""),
            start_date=start,
            end_date=end,
            highlights=html_to_bullets(e.get("description", "")),
        ))

    education = []
    for e in items("education"):
        start, end = split_period(e.get("period", ""))
        education.append(Education(
            institution=e.get("school", ""),
            area=e.get("area", ""),
            study_type=e.get("degree", ""),
            start_date=start,
            end_date=end,
            gpa=e.get("grade", ""),
        ))

    projects = []
    for p in items("projects"):
        raw = p.get("description", "") or ""
        bullets = html_to_bullets(raw)
        first_li = _LI.search(raw)
        if first_li:
                                                                         
            description, highlights = _strip_html(raw[:first_li.start()]), bullets
        else:
            description, highlights = " ".join(bullets), []
        projects.append(Project(
            name=p.get("name", ""),
            description=description,
            url=(p.get("website") or {}).get("url", ""),
            highlights=highlights,
        ))

    return Resume(
        basics=Basics(
            name=basics.get("name", ""),
            email=basics.get("email", ""),
            phone=basics.get("phone", ""),
            location=basics.get("location", ""),
            website=website or "",
            linkedin=linkedin,
            github=github,
        ),
        summary=Summary(content=_strip_html((doc.get("summary") or {}).get("content", ""))),
        experience=experience,
        education=education,
        skills=[
            SkillCategory(name=s.get("name", ""), keywords=s.get("keywords") or [])
            for s in items("skills")
        ],
        projects=projects,
    )


if __name__ == "__main__":
    original = Resume(
        basics=Basics(
            name="Priya Sharma", email="p@example.com", phone="+91 90000 00000",
            location="Bengaluru, India", website="https://priya.dev",
            linkedin="https://linkedin.com/in/priyasharma", github="priyasharma",
        ),
        summary=Summary(content="Marketing lead with 4 years of experience."),
        experience=[Experience(
            company="Acme", position="Marketing Lead", location="Remote",
            start_date="Jan 2022", end_date="Present",
            highlights=["Grew engagement 150%", "Ran a team of 4"],
        )],
        education=[Education(
            institution="IIT Bombay", area="Computer Science", study_type="B.Tech",
            start_date="2016", end_date="2020", gpa="8.9",
        )],
        skills=[SkillCategory(name="Languages", keywords=["Python", "Go"])],
        projects=[Project(
            name="Dashboard", description="Internal analytics tool",
            url="https://github.com/p/dash", highlights=["Cut load time 40%"],
        )],
    )

    doc = to_rxresume(original)

                            
    assert set(doc) >= {"picture", "basics", "summary", "sections", "customSections", "metadata"}
    assert set(doc["sections"]) == set(SECTION_TITLES), set(doc["sections"]) ^ set(SECTION_TITLES)
    assert set(doc["metadata"]) == {"template", "layout", "page", "design", "typography", "notes"}
    for key, sec in doc["sections"].items():
        assert set(sec) == {"title", "columns", "hidden", "items"}, key
    assert doc["sections"]["languages"]["items"] == [] and doc["sections"]["languages"]["hidden"]
    assert doc["metadata"]["layout"]["pages"][0]["sidebar"] == [], "must stay single-column for ATS"

                                            
    assert doc["sections"]["education"]["items"][0]["school"] == "IIT Bombay"
    assert doc["sections"]["education"]["items"][0]["degree"] == "B.Tech"
    assert doc["sections"]["education"]["items"][0]["grade"] == "8.9"
    assert doc["sections"]["experience"]["items"][0]["period"] == "Jan 2022 - Present"
    assert "<li>Grew engagement 150%</li>" in doc["sections"]["experience"]["items"][0]["description"]
    assert doc["sections"]["profiles"]["items"][0]["username"] == "priyasharma"
    assert doc["sections"]["profiles"]["items"][1]["website"]["url"] == "https://github.com/priyasharma"

                                   
    assert to_rxresume(original)["sections"]["experience"]["items"][0]["id"] ==\
        doc["sections"]["experience"]["items"][0]["id"]

                                                     
    back = from_rxresume(doc)
    assert back.basics.name == original.basics.name
    assert back.basics.github == "https://github.com/priyasharma"
    assert back.summary.content == original.summary.content
    assert back.experience[0].start_date == "Jan 2022"
    assert back.experience[0].end_date == "Present"
    assert back.experience[0].highlights == original.experience[0].highlights
    assert back.education[0].institution == "IIT Bombay"
    assert back.education[0].study_type == "B.Tech"
    assert back.education[0].gpa == "8.9"
    assert back.skills[0].keywords == ["Python", "Go"]
    assert back.projects[0].highlights == ["Cut load time 40%"]
    assert back.projects[0].url == "https://github.com/p/dash"
                                               
    assert back.projects[0].description == "Internal analytics tool", back.projects[0].description

                               
    assert split_period("2016 – 2020") == ("2016", "2020")
    assert split_period("2016-2020") == ("2016", "2020")
    assert split_period("Jan 2020 to Present") == ("Jan 2020", "Present")
    assert split_period("2020") == ("2020", "")
    assert split_period("") == ("", "")

                                                              
    assert html_to_bullets("<p>One thing</p><p>Another</p>") == ["One thing", "Another"]
    assert looks_like_rxresume(doc) and not looks_like_rxresume({"basics": {}})

    print("rxresume adapter ok")