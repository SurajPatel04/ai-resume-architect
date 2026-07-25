import logging
import tempfile
import os
import subprocess
from typing import Any, Dict
from app.graphs.state import ResumeState

logger = logging.getLogger(__name__)

def render_resume(state: ResumeState) -> Dict[str, Any]:
    """
    Renders the tailored resume (if available) or master_profile into a PDF using Typst.
    """
    logger.info("Rendering resume to PDF...")
    
    generated = state.get("generated_resumes", {})
    resume = generated.get("tailored") or state.get("master_profile", {})
    if hasattr(resume, "model_dump"):
        r = resume.model_dump()
    else:
        r = resume

    basics = r.get("basics", {})
    experience = r.get("experience", [])
    education = r.get("education", [])
    skills = r.get("skills", [])
    projects = r.get("projects", [])
    summary = r.get("summary", {}).get("content", "")

    # Clean up fields for Typst
    def escape_typst(text: str) -> str:
        if not text:
            return ""
        # Escape all Typst special characters that could break markup
        # Note: +, =, and - are ONLY special if followed by space at the start of a line.
        # Escaping them as \+, \=, \- breaks them (e.g., \- becomes a soft hyphen, \+ renders weirdly).
        for char in ['\\', '*', '_', '$', '<', '>', '@', '[', ']', '#']:
            text = text.replace(char, '\\' + char)
        return text

    # Build Typst template
    typst_code = f"""
#set document(title: "{escape_typst(basics.get('name', 'Resume'))}")
#set page(margin: (x: 0.9in, y: 0.9in))
#set text(size: 11pt)

#show heading: it => [
  #set text(size: 11pt, weight: "regular")
  #block(smallcaps(it.body))
  #v(-0.2em)
  #line(length: 100%, stroke: 0.5pt)
  #v(0.1em)
]

#align(center)[
  #text(16pt, weight: "bold")[{escape_typst(basics.get('name', ''))}]
  
  {escape_typst(basics.get('location', ''))} | {escape_typst(basics.get('phone', ''))} | {escape_typst(basics.get('email', ''))}
  
  {escape_typst(basics.get('linkedin', ''))} | {escape_typst(basics.get('github', ''))}
]

"""

    if summary:
        typst_code += f"""
= Summary
{escape_typst(summary)}
"""

    if experience:
        typst_code += "\n= Experience\n"
        for exp in experience:
            typst_code += f"""
*{escape_typst(exp.get('company', ''))}* #h(1fr) {escape_typst(exp.get('start_date', ''))} \\- {escape_typst(exp.get('end_date', ''))} \\
_{escape_typst(exp.get('position', ''))}_, {escape_typst(exp.get('location', ''))}
"""
            for hl in exp.get("highlights", []):
                typst_code += f"- {escape_typst(hl)}\n"

    if education:
        typst_code += "\n= Education\n"
        for edu in education:
            typst_code += f"""
*{escape_typst(edu.get('institution', ''))}* #h(1fr) {escape_typst(edu.get('start_date', ''))} \\- {escape_typst(edu.get('end_date', ''))} \\
{escape_typst(edu.get('study_type', ''))} in {escape_typst(edu.get('area', ''))}
"""
            if edu.get("gpa"):
                typst_code += f"- GPA: {escape_typst(edu.get('gpa'))}\n"

    if projects:
        typst_code += "\n= Projects\n"
        for proj in projects:
            typst_code += f"""
*{escape_typst(proj.get('name', ''))}* #h(1fr) {escape_typst(proj.get('url', ''))}
"""
            for hl in proj.get("highlights", []):
                typst_code += f"- {escape_typst(hl)}\n"

    if skills:
        typst_code += "\n= Skills\n"
        for skill in skills:
            typst_code += f"""
- *{escape_typst(skill.get('name', ''))}*: {escape_typst(', '.join(skill.get('keywords', [])))}
"""

    # Compile with Typst
    try:
        from uuid import uuid4
        
        # Make static/pdfs directory
        pdf_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static", "pdfs")
        os.makedirs(pdf_dir, exist_ok=True)
        
        session_id = state.get("session_id", uuid4().hex)
        filename = f"{session_id}.pdf"
        typ_filename = f"{session_id}.typ"
        
        typ_path = os.path.join(pdf_dir, typ_filename)
        pdf_fs_path = os.path.join(pdf_dir, filename)

        with open(typ_path, 'w', encoding='utf-8') as f:
            f.write(typst_code)
            
        subprocess.run(["typst", "compile", typ_path, pdf_fs_path], check=True, capture_output=True)
        
        return {
            "phase": "completed",
            "pdf_path": f"http://localhost:8000/pdfs/{filename}"
        }
    except Exception as e:
        logger.error(f"Failed to compile Typst: {e}")
        return {"phase": "completed"}
