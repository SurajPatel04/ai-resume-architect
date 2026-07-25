from typing import Any, Dict, List, Literal, Optional, TypedDict
from pydantic import BaseModel, Field

# -----------------------------------------------------------------------------
# Resume Pydantic Models (Single Source of Truth)
# -----------------------------------------------------------------------------

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

class Resume(BaseModel):
    basics: Basics = Field(default_factory=Basics, description="Basic personal details and contact information")
    summary: Summary = Field(default_factory=Summary, description="Professional summary section")
    experience: List[Experience] = Field(default_factory=list, description="Work experience history in reverse chronological order")
    education: List[Education] = Field(default_factory=list, description="Education history and academic credentials")
    skills: List[SkillCategory] = Field(default_factory=list, description="List of technical and soft skills grouped by category (e.g., Languages, Frameworks, Tools)")
    projects: List[Project] = Field(default_factory=list, description="Notable personal, academic, or open-source projects")

# Factory function to create an empty resume structure
def new_resume() -> Resume:
    return Resume()


# -----------------------------------------------------------------------------
# LangGraph State Schema
# -----------------------------------------------------------------------------

class ResumeState(TypedDict):
    # Session
    session_id: str
    user_id: Optional[str]

    # Target Job
    job_description: Optional[str]

    # Conversation
    messages: List[Dict[str, Any]]
    latest_answer: Optional[str]

    # Planner State
    workflow_type: Optional[Literal["BUILD_PROFILE", "TAILOR_RESUME"]]
    workflow: Optional[str]
    current_step: Optional[str]
    completion: int

    # Current profile (The single source of truth)
    master_profile: Resume

    # Generated tailored resumes
    generated_resumes: Dict[str, Resume]
    resume_versions: List[Dict[str, Any]]

    # Uploaded document (only used during parsing)
    uploaded_file: Optional[str]
    uploaded_text: Optional[str]

    # Planner
    tasks: List[Dict[str, Any]]
    current_task: Optional[Dict[str, Any]]

    # Gaps Architecture
    question_queue: List[Dict[str, Any]]
    skipped: List[str]
    active_target: Optional[Dict[str, Any]]

    # Current question (sent to frontend)
    current_question: Optional[Dict[str, Any]]

    # Validation
    extracted_entities: Dict[str, Any]
    validation_errors: List[str]
    pending_verifications: List[Dict[str, Any]]

    # Conversation status
    phase: Literal[
        "collecting",
        "enhancing",
        "rendering",
        "completed"
    ]

    # Resume outputs
    ats_score: Optional[int]
    generated_resume: Optional[str]
    pdf_path: Optional[str]
