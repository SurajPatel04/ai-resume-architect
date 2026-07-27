/**
 * Mirrors the backend `Resume` schema in app/graphs/state.py.
 *
 * Every field is optional here: the profile is streamed while it is still being
 * filled in, so the UI sees partial versions of it on almost every turn.
 */

export interface ResumeBasics {
    name?: string;
    email?: string;
    phone?: string;
    location?: string;
    website?: string;
    linkedin?: string;
    github?: string;
}

export interface ResumeExperience {
    company?: string;
    position?: string;
    location?: string;
    start_date?: string;
    end_date?: string;
    highlights?: string[];
}

export interface ResumeEducation {
    institution?: string;
    area?: string;
    study_type?: string;
    start_date?: string;
    end_date?: string;
    gpa?: string;
}

export interface ResumeProject {
    name?: string;
    description?: string;
    url?: string;
    highlights?: string[];
}

export interface ResumeSkillCategory {
    name?: string;
    keywords?: string[];
}

export interface Resume {
    basics?: ResumeBasics;
    summary?: { content?: string };
    experience?: ResumeExperience[];
    education?: ResumeEducation[];
    skills?: ResumeSkillCategory[];
    projects?: ResumeProject[];
}