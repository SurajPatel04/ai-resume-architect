"""The finished resume, as a one-column serif PDF built with Typst.

Deliberately plain: a centred name over two contact lines, then ruled section headings
with the role on the left and the dates on the right. That is the arrangement recruiters
and ATS parsers both read without complaint, and it is what the layout below reproduces.

The document is assembled as a string rather than a template file so escaping and the
"leave it out when it is empty" rules live next to the data they apply to — a template
with a dangling `|` between two blank fields is the failure this shape avoids.
"""

import logging
import os
import subprocess
from typing import Any, Dict, List

from app.core.config import settings
from app.graphs.state import ResumeState

logger = logging.getLogger(__name__)

FONTS = '("New Computer Modern", "Libertinus Serif", "Linux Libertine", "Georgia")'

SUBTITLE_MAX = 60

def escape_typst(text: Any) -> str:
    """Neutralise Typst markup in user text.

    Backslash first, or every escape added below gets escaped again on the next pass.
    """
    if not text:
        return ""
    out = str(text)
    for char in ("\\", "*", "_", "$", "<", ">", "@", "[", "]", "#", "`"):
        out = out.replace(char, "\\" + char)
    return out

def joined(*parts: Any, sep: str = "  |  ") -> str:
    """Escaped parts with separators only between the ones that exist.

    An unconditional `a | b | c` on a profile with no GitHub renders "  |  |  ", which is
    the first thing anyone notices on a printed resume.
    """
    return sep.join(escape_typst(p) for p in parts if p and str(p).strip())

def date_range(start: Any, end: Any) -> str:
    """'Jul 2024 – Jun 2026', or whichever half exists."""
    return " – ".join(str(x).strip() for x in (start, end) if x and str(x).strip())

def dated(left: str, right: str) -> str:
    """A title row: markup on the left, dates pushed to the right margin."""
    right = escape_typst(right)
    return f"{left} #h(1fr) {right}" if right else left

def rows(*lines: str) -> str:
    """Stack lines inside one entry, tight, using Typst's linebreak."""
    return " \\\n".join(line for line in lines if line)

def bullets(items: Any) -> List[str]:
    return [f"- {escape_typst(item)}" for item in (items or []) if str(item).strip()]

def _header(basics: Dict[str, Any]) -> List[str]:
    name = escape_typst(basics.get("name"))
    contact = joined(basics.get("location"), basics.get("phone"), basics.get("email"))
    links = joined(basics.get("website"), basics.get("github"), basics.get("linkedin"))

    stack = [f'#text(size: 21pt, weight: "bold")[{name}]']
    for line in (contact, links):
        if line:
            stack.append(f"#text(size: 9pt)[{line}]")

    return ["#align(center)[", "  " + " \\\n  ".join(stack), "]"]

def _skills(skills: List[Dict[str, Any]]) -> List[str]:
    lines = []
    for category in skills or []:
        keywords = ", ".join(str(k).strip() for k in (category.get("keywords") or []) if str(k).strip())
        if not keywords:
            continue
        label = escape_typst(category.get("name")) or "Skills"
        lines.append(f"*{label}:* {escape_typst(keywords)}")
    return [rows(*lines)] if lines else []

def _experience(experience: List[Dict[str, Any]]) -> List[str]:
    body: List[str] = []
    for job in experience or []:
                                                                                         
        title = escape_typst(job.get("position")) or escape_typst(job.get("company"))
        if not title and not job.get("highlights"):
            continue

        under = escape_typst(job.get("company")) if job.get("position") else ""
        place = escape_typst(job.get("location"))
        if place:
            under = f"{under}, {place}" if under else place

        body.append(rows(
            dated(f"*{title}*", date_range(job.get("start_date"), job.get("end_date"))),
            f"_{under}_" if under else "",
        ))
        body.extend(bullets(job.get("highlights")))
        body.append("")
    return body

def _projects(projects: List[Dict[str, Any]]) -> List[str]:
    body: List[str] = []
    for project in projects or []:
        name = escape_typst(project.get("name"))
        if not name and not project.get("highlights"):
            continue

        description = (project.get("description") or "").strip()
        subtitle = escape_typst(description) if 0 < len(description) <= SUBTITLE_MAX else ""

        body.append(rows(
            f"*{name}* – {subtitle}" if subtitle else f"*{name}*",
            f'#text(size: 8.5pt)[{escape_typst(project.get("url"))}]' if project.get("url") else "",
        ))
        if description and not subtitle:
            body.append(escape_typst(description))
        body.extend(bullets(project.get("highlights")))
        body.append("")
    return body

def _education(education: List[Dict[str, Any]]) -> List[str]:
    body: List[str] = []
    for entry in education or []:
        degree = escape_typst(entry.get("study_type"))
        area = escape_typst(entry.get("area"))
        title = " in ".join(x for x in (degree, area) if x) or escape_typst(entry.get("institution"))
        if not title:
            continue

        institution = escape_typst(entry.get("institution"))
                                                                                      
        under = f"_{institution}_" if institution and title != institution else ""
        if entry.get("gpa"):
            grade = escape_typst(f"GPA: {entry['gpa']}")
            under = f"{under} #h(1fr) _{grade}_" if under else f"_{grade}_"

        body.append(rows(
            dated(f"*{title}*", date_range(entry.get("start_date"), entry.get("end_date"))),
            under,
        ))
        body.append("")
    return body

def _certifications(certifications: List[Dict[str, Any]]) -> List[str]:
    body: List[str] = []
    for cert in certifications or []:
        name = escape_typst(cert.get("name"))
        if not name:
            continue
        issuer = escape_typst(cert.get("issuer"))
        credential_url = escape_typst(cert.get("url"))
        details = issuer
        if credential_url:
            details = f"{details} | Credential: {credential_url}" if details else f"Credential: {credential_url}"
        body.append(rows(
            dated(f"*{name}*", cert.get("date") or ""),
            f'_{details}_' if details else "",
        ))
        body.append("")
    return body

def build_typst(r: Dict[str, Any]) -> str:
    """The whole document. Pure, so the layout can be checked without a PDF."""
    basics = r.get("basics") or {}
    summary = ((r.get("summary") or {}).get("content") or "").strip()

    out = [
        f'#set document(title: "{escape_typst(basics.get("name")) or "Resume"}")',
        "#set page(margin: (x: 0.6in, y: 0.55in))",
        f"#set text(font: {FONTS}, size: 10pt)",
        "#set par(leading: 0.6em, justify: false)",
        "#set list(marker: [•], indent: 0.2em, body-indent: 0.45em, spacing: 0.5em)",
        "",
                                                               
        "#show heading: it => block(above: 1em, below: 0.6em, width: 100%)[",
        '  #text(size: 12.5pt, weight: "bold")[#it.body]',
        "  #v(-0.62em)",
        "  #line(length: 100%, stroke: 0.7pt)",
        "]",
        "",
        *_header(basics),
    ]

    sections = (
        ("Profile Summary", [escape_typst(summary)] if summary else []),
        ("Technical Skills", _skills(r.get("skills"))),
        ("Professional Experience", _experience(r.get("experience"))),
        ("Projects", _projects(r.get("projects"))),
        ("Education", _education(r.get("education"))),
        ("Certifications", _certifications(r.get("certifications"))),
    )

    for title, body in sections:
        if not any(line.strip() for line in body):
            continue
        out.append("")
        out.append(f"= {title}")
                                                                                       
        out.append("#pad(left: 0.5em)[")
        out.extend(body)
        out.append("]")

    return "\n".join(out) + "\n"

def render_resume(state: ResumeState) -> Dict[str, Any]:
    """Renders the tailored resume, or the master profile, into a PDF using Typst."""
    logger.info("Rendering resume to PDF...")

    generated = state.get("generated_resumes", {})
    resume = generated.get("tailored") or state.get("master_profile", {})
    r = resume.model_dump() if hasattr(resume, "model_dump") else resume

    typst_code = build_typst(r or {})

    try:
        from uuid import uuid4

        pdf_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static", "pdfs")
        os.makedirs(pdf_dir, exist_ok=True)

        session_id = state.get("session_id", uuid4().hex)
        filename = f"{session_id}.pdf"
        typ_path = os.path.join(pdf_dir, f"{session_id}.typ")
        pdf_fs_path = os.path.join(pdf_dir, filename)

        with open(typ_path, "w", encoding="utf-8") as f:
            f.write(typst_code)

        subprocess.run(["typst", "compile", typ_path, pdf_fs_path], check=True, capture_output=True)
        os.remove(typ_path)

        return {
            "phase": "completed",
            "pdf_path": f"{settings.PUBLIC_BASE_URL}/pdfs/{filename}",
            "render_error": None,
        }
    except FileNotFoundError:
                                                                       
        logger.error("The `typst` binary is not on PATH — no PDF can be produced.")
        return {"phase": "completed", "render_error": "The PDF renderer is not available on the server."}
    except subprocess.CalledProcessError as e:
                                                                                        
        logger.error("Typst compile failed: %s", (e.stderr or b"").decode(errors="replace"))
        return {"phase": "completed", "render_error": "The resume could not be compiled to PDF."}
    except Exception as e:
        logger.error(f"Failed to render resume: {e}")
        return {"phase": "completed", "render_error": "The resume could not be compiled to PDF."}

if __name__ == "__main__":
    PROFILE = {
        "basics": {"name": "Suraj Patel", "email": "s@example.com", "phone": "+91 9260923895",
                   "location": "Lucknow, Uttar Pradesh, India", "website": "surajpatel.dev",
                   "github": "github.com/SurajPatel04", "linkedin": "linkedin.com/in/suraj-patel"},
        "summary": {"content": "Software Engineer focused on agentic AI workflows."},
        "skills": [{"name": "Languages", "keywords": ["JavaScript", "TypeScript", "Python"]},
                   {"name": "Frontend", "keywords": ["React", "Redux"]}],
        "experience": [{"company": "Careerboat", "position": "Full Stack Engineer",
                        "location": "", "start_date": "Dec 2025", "end_date": "Present",
                        "highlights": ["Cut LLM token consumption by 40%"]}],
        "projects": [{"name": "InsightFlow", "description": "Multimodal RAG Platform",
                      "url": "github.com/SurajPatel04/rag", "highlights": ["Engineered a RAG platform"]}],
        "education": [{"institution": "Amity University Online", "area": "",
                       "study_type": "Master of Computer Applications (MCA)",
                       "start_date": "Jul 2024", "end_date": "Jun 2026", "gpa": ""}],
        "certifications": [],
    }

    doc = build_typst(PROFILE)

    assert "Suraj Patel" in doc
                                                                                        
    assert "Lucknow, Uttar Pradesh, India  |  +91 9260923895  |  s\\@example.com" in doc
                                                                                     
    assert "surajpatel.dev  |  github.com/SurajPatel04  |  linkedin.com/in/suraj-patel" in doc

    assert joined("Delhi", "", None) == "Delhi"
    assert joined(None, "", "  ") == ""
    assert joined("a", "b") == "a  |  b"
    bare = build_typst({"basics": {"name": "S", "location": "Delhi"}})
    assert "|" not in bare, bare

    for title in ("Profile Summary", "Technical Skills", "Professional Experience",
                  "Projects", "Education"):
        assert f"= {title}" in doc, title
                                                               
    assert "= Certifications" not in doc
    assert "= Projects" not in build_typst({"basics": {"name": "S"}})

    assert "*Full Stack Engineer* #h(1fr) Dec 2025 – Present" in doc, doc
    assert "_Careerboat_" in doc
    assert "*Languages:* JavaScript, TypeScript, Python" in doc
    assert "*Master of Computer Applications (MCA)* #h(1fr) Jul 2024 – Jun 2026" in doc
    assert "*InsightFlow* – Multimodal RAG Platform" in doc

    assert date_range("2020", "") == "2020" and date_range("", "2024") == "2024"
    assert date_range("", "") == ""
    assert dated("*X*", "") == "*X*", "no dates, no #h(1fr) pushing nothing to the margin"

    wordy = build_typst({"basics": {"name": "S"}, "projects": [
        {"name": "Thing", "description": "x" * 200, "highlights": []}]})
    assert "*Thing* –" not in wordy, "a 200-character subtitle would wrap into the title"
    assert "x" * 200 in wordy, "and it must still appear somewhere"

    nasty = build_typst({"basics": {"name": "A*B_C#D", "email": "a@b.com"}})
    assert "A\\*B\\_C\\#D" in nasty, nasty
    assert "a\\@b.com" in nasty
    assert escape_typst("C:\\path") == "C:\\\\path", "backslash escaped first, and only once"
    assert escape_typst("") == "" and escape_typst(None) == ""

    assert doc.count("[") - doc.count("\\[") == doc.count("]") - doc.count("\\]"), doc

    print("render_resume ok")
