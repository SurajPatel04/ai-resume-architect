from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict
from pydantic import BaseModel, Field

def merge_usage(left: Optional[Dict[str, int]], right: Optional[Dict[str, int]]) -> Dict[str, int]:
    """Reducer for `usage`: token counts add up instead of overwriting."""
    left, right = left or {}, right or {}
    return {
        key: left.get(key, 0) + right.get(key, 0)
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }

class Basics(BaseModel):
    name: str = Field(default="", description="Full name of the candidate")
    email: str = Field(default="", description="Email address")
    phone: str = Field(default="", description="Phone number with country code if available")
    location: str = Field(default="", description="City, State, Country or location of residence")
    website: str = Field(default="", description="Personal website or portfolio URL")
    linkedin: str = Field(default="", description="LinkedIn profile URL or username")
    github: str = Field(default="", description="GitHub profile URL or username")

class Summary(BaseModel):
    content: str = Field(default="", description="Professional summary or objective statement from the resume")

class Experience(BaseModel):
    company: str = Field(default="", description="Name of the company or organization")
    position: str = Field(default="", description="Job title or role held")
    location: str = Field(default="", description="Location of the job (e.g. City, State or Remote)")
    start_date: str = Field(default="", description="Start date, formatted as Month Year or YYYY")
    end_date: str = Field(default="", description="End date (e.g. Month Year, YYYY, or 'Present')")
    highlights: List[str] = Field(default_factory=list, description="Key bullet points, achievements, and responsibilities for this role")

class Education(BaseModel):
    institution: str = Field(default="", description="Name of the university, college, or educational institution")
    area: str = Field(default="", description="Field of study or major (e.g. Computer Science, Business)")
    study_type: str = Field(default="", description="Degree or credential earned (e.g. Bachelor of Science, Master's)")
    start_date: str = Field(default="", description="Start date, formatted as Month Year or YYYY")
    end_date: str = Field(default="", description="End date or Graduation date, formatted as Month Year or YYYY")
    gpa: str = Field(default="", description="GPA or grade score if explicitly mentioned")

class Project(BaseModel):
    name: str = Field(default="", description="Title or name of the project")
    description: str = Field(default="", description="Brief summary of what the project does and technologies used")
    url: str = Field(default="", description="URL link to the project repository or live site")
    highlights: List[str] = Field(default_factory=list, description="Bullet points detailing achievements, features, or metrics of the project")

class SkillCategory(BaseModel):
    name: str = Field(default="", description="Name of the skill category (e.g., Languages, Frontend, Backend, Tools & DevOps)")
    keywords: List[str] = Field(default_factory=list, description="List of skills in this category")

class Certification(BaseModel):
    name: str = Field(default="", description="Name of the certification, licence or award, e.g. 'AWS Certified Solutions Architect – Associate'")
    issuer: str = Field(default="", description="Organisation that issued or awarded it, e.g. 'Amazon Web Services'")
    date: str = Field(default="", description="Date earned, or validity period, as written on the resume")
    url: str = Field(default="", description="Public credential or verification URL, if the candidate provides one")

class CustomEntry(BaseModel):
    title: str = Field(default="", description="What this entry is called — the award, the role, the publication title")
    subtitle: str = Field(default="", description="Who it was with or for: the organisation, publisher, or issuing body")
    date: str = Field(default="", description="Date or period, exactly as the candidate wrote it")
    highlights: List[str] = Field(default_factory=list, description="Bullet points about this entry, if there are any")

class CustomSection(BaseModel):
    """A section this schema does not model: Volunteering, Awards, Publications, Languages.

    Resumes carry sections nobody can enumerate in advance. Dropping them on import
    loses work the candidate chose to put on the page, so they are kept as named
    groups of entries and rendered in the same shape as everything else.
    """

    name: str = Field(default="", description="The section heading as the resume writes it, e.g. 'Volunteering'")
    entries: List[CustomEntry] = Field(default_factory=list, description="The entries listed under that heading")

class Resume(BaseModel):
    basics: Basics = Field(default_factory=Basics, description="Basic personal details and contact information")
    summary: Summary = Field(default_factory=Summary, description="Professional summary section")
    experience: List[Experience] = Field(default_factory=list, description="Work experience history in reverse chronological order")
    education: List[Education] = Field(default_factory=list, description="Education history and academic credentials")
    skills: List[SkillCategory] = Field(default_factory=list, description="List of technical and soft skills grouped by category (e.g., Languages, Frameworks, Tools)")
    projects: List[Project] = Field(default_factory=list, description="Notable personal, academic, or open-source projects")

    certifications: List[Certification] = Field(default_factory=list, description="Certifications, licences, awards and honours")

    custom_sections: List[CustomSection] = Field(
        default_factory=list,
        description="Any other section the resume has that the fields above do not cover — "
        "Volunteering, Awards, Publications, Languages, Interests, Achievements. Keep the "
        "heading the resume uses. Never duplicate here anything already captured above.",
    )

LIST_SECTIONS = {
    "experience": Experience,
    "education": Education,
    "projects": Project,
}

SECTION_MODELS = {"basics": Basics, "summary": Summary,
                  "certifications": Certification, **LIST_SECTIONS}

def new_resume() -> Dict[str, Any]:
    """The empty profile, as a plain dict."""
    return Resume().model_dump()

class ResumeState(TypedDict):

    session_id: str
    user_id: Optional[str]

    job_description: Optional[str]

    latest_answer: Optional[str]

    # Set by the planner when a message carries a whole new entry to file.
    add_section: Optional[str]

    workflow_type: Optional[Literal["BUILD_PROFILE", "TAILOR_RESUME", "EDIT_PROFILE"]]
    workflow: Optional[str]
    current_step: Optional[str]
    completion: int

    # A dict, not a Resume: nothing pydantic reaches the checkpoint. See new_resume().
    master_profile: Dict[str, Any]

    generated_resumes: Dict[str, Resume]
    resume_versions: List[Dict[str, Any]]

    uploaded_file: Optional[str]
    uploaded_text: Optional[str]

    tasks: List[Dict[str, Any]]
    current_task: Optional[Dict[str, Any]]

    seniority: Optional[str]

    career_level: Optional[Literal["fresher", "internship", "experienced"]]

    target_role: Optional[str]

    import_confirmed: Optional[bool]

    question_queue: List[Dict[str, Any]]
    skipped: List[str]
    active_target: Optional[Dict[str, Any]]

    exchanges: List[Dict[str, Any]]

    follow_ups_asked: int

    current_question: Optional[Dict[str, Any]]

    extracted_entities: Dict[str, Any]
    validation_errors: List[str]
    pending_verifications: List[Dict[str, Any]]

    phase: Literal[
        "collecting",
        "enhancing",
        "rendering",
        "completed"
    ]

    ats_score: Optional[int]
    ats_feedback: Optional[Dict[str, Any]]

    quality_score: Optional[int]
    quality_feedback: Optional[List[Dict[str, Any]]]
    generated_resume: Optional[str]
    pdf_path: Optional[str]

    render_error: Optional[str]

    # Render-only: sections left off the PDF, and the two-page escape hatch.
    dropped_sections: List[str]
    page_limit_waived: Optional[bool]
    bullet_cap: Optional[int]
    dropped_entries: List[str]

    # The uploaded PDF kept for choose_style, and what the user decided about it.
    source_pdf: Optional[str]
    style_choice: Optional[Literal["site", "mine"]]
    style_spec: Optional[Dict[str, Any]]

    edit_applied: Optional[bool]

    quality_reviewed: Optional[bool]

    skill_gap_asked: Optional[bool]

    extras_offered: Optional[bool]

    usage: Annotated[Dict[str, int], merge_usage]
