import logging
import re
from typing import Any, Dict, List

from app.graphs.state import ResumeState, Resume
from app.utils.llm import get_openai_llm
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_NUMBER = re.compile(r"\d+(?:\.\d+)?")

MAX_BULLETS = 4

def numbers_in(text: str) -> set:
    """Every figure in a bullet. Commas stripped so 1,000 and 1000 are the same number."""
    return set(_NUMBER.findall((text or "").replace(",", "")))

def keep_honest(original: str, rewritten: str) -> str:
    """Discard a rewrite that introduces a figure the original never had.

    The prompt tells the model not to invent. It invents anyway. A number is the one
    kind of fabrication that can be caught exactly and cheaply, and the one that does
    the most damage when someone is asked about it in an interview.
    """
    if numbers_in(rewritten) <= numbers_in(original):
        return rewritten
    logger.warning("Dropped a rewrite that invented a figure: %r", rewritten)
    return original

def honest_highlights(originals: List[str], rewritten: List[str]) -> List[str]:
    """The polished bullets, minus anything that invented a figure, capped at MAX_BULLETS.

    Two shapes, because the enhancer is now allowed to merge weak lines into strong ones:

    - Same count: rewrites pair back to their source, and one that invents a figure is
      replaced by the line it came from.
    - Condensed: nothing pairs, so figures are checked against everything the entry
      originally said. A number moving between two of the candidate's own bullets is a
      rewrite; one appearing from nowhere is a fabrication they get asked about.

    Padding the result back up to the original count is what put the raw paste on the
    page: the enhancer condensed fourteen shredded lines into four, and the other ten
    were "restored" verbatim underneath them.
    """
    if not rewritten:
        return list(originals[:MAX_BULLETS])

    if len(rewritten) == len(originals):
        kept = [keep_honest(o, n) for o, n in zip(originals, rewritten)]
    else:
        allowed = set().union(*(numbers_in(o) for o in originals))
        kept = [r for r in rewritten if r.strip() and numbers_in(r) <= allowed]
        if len(kept) < len(rewritten):
            logger.warning("Dropped %d rewrite(s) that invented a figure.",
                           len(rewritten) - len(kept))

    return kept[:MAX_BULLETS] or list(originals[:MAX_BULLETS])

class EnhancedExperience(BaseModel):
    highlights: List[str] = Field(
        description=f"At most {MAX_BULLETS} polished highlights for this experience, strongest first."
    )

class EnhancedProject(BaseModel):
    highlights: List[str] = Field(
        description=f"At most {MAX_BULLETS} polished highlights for this project, strongest first."
    )

class SkillGroup(BaseModel):
    name: str = Field(
        description="Heading for this group, e.g. Languages, Frontend, Backend, Databases, "
        "Cloud & DevOps, AI & Data, Tools. Name the group after what is actually in it."
    )
    keywords: List[str] = Field(description="The skills in this group, spelled exactly as given.")

class EnhancedResume(BaseModel):
    summary_content: str = Field(description="Polished professional summary")
    experience: List[EnhancedExperience] = Field(description="List of enhanced experiences, in the same order as provided")
    projects: List[EnhancedProject] = Field(description="List of enhanced projects, in the same order as provided")
                                                                                        
    skills: List[SkillGroup] = Field(
        default_factory=list,
        description="Every skill the candidate already has, regrouped under sensible headings. "
        "Move skills between groups freely, but never add one they did not list and never "
        "drop one they did — the set must come out exactly as it went in.",
    )

def regrouped(original: List[dict], groups: List[SkillGroup]) -> List[dict]:
    """The regrouped skills, or the originals if a single one was invented or lost.

    Filing Redis under Databases is worth a line of prompt; quietly deleting a skill
    someone told us they have is not, so the whole regrouping is discarded unless the set
    comes back identical. Same shape as the number check above: cheap, exact, and it
    fails closed.
    """
    def names(categories) -> set:
        return {
            str(k).strip().lower()
            for c in categories
            for k in ((c.get("keywords") if isinstance(c, dict) else c.keywords) or [])
            if str(k).strip()
        }

    if not groups:
        return original

    if names(groups) != names(original):
        logger.warning("Skill regrouping changed the set of skills; keeping the original grouping.")
        return original

    return [{"name": g.name.strip() or "Skills", "keywords": list(g.keywords)}
            for g in groups if g.keywords]

def enhance_resume(state: ResumeState) -> Dict[str, Any]:
    """
    Polishes the resume's bullets and summary for maximum impact using the LLM.
    Scoping the output to prevent hallucinated data loss of factual fields.
    """
    logger.info("Enhancing resume...")

    generated = dict(state.get("generated_resumes") or {})
    target = generated.get("tailored")
    onto_tailored = target is not None
    if not onto_tailored:
        target = state.get("master_profile", {})

    r = target.model_dump() if hasattr(target, "model_dump") else dict(target)

    llm = get_openai_llm()
    structured_llm = llm.with_structured_output(EnhancedResume)

    prompt = f"""
    You are an expert resume writer. The user has provided their resume information.
    Your task is to heavily polish the professional summary, and the highlights/bullet points of their experience and projects.
    
    Guidelines:
    1. Rewrite highlights to use strong action verbs.
    2. Lead with the result WHEN THE BULLET ALREADY STATES ONE. Asking for a Result on
       every bullet is what makes a writer invent outcomes — a bullet with no stated
       outcome gets better wording and nothing else. No trailing "improving X",
       "enhancing Y", "optimizing Z" unless the input says so.
    3. Make the summary highly impactful and concise (3-4 sentences max).
    4. Fix any grammatical errors.
    5. Every number, percentage, timespan and claim in your output must trace to the input.
       Invent nothing. This is someone's real resume and they will be asked about it.
    6. Return AT MOST {MAX_BULLETS} highlights per entry, strongest first. People paste
       whole sections out of an old resume, and the job here is to turn that into the
       handful of lines worth reading — merge overlapping bullets, fold a weak one into
       the strong one next to it, and drop filler outright. Never split one bullet into
       several, and never return more than you were given.
    7. Rewrite. A bullet returned word for word as it came in has not been enhanced.
    8. Regroup the skills under headings that describe them — Languages, Frontend,
       Backend, Databases, Cloud & DevOps, AI & Data, Tools, or whatever actually fits
       what is there. Every skill in, every skill out: change the grouping, never the set.

    Here is the current raw resume data:
    {r}

    Output the enhanced fields in the exact same order as the raw data arrays.
    """

    try:
        enhanced: EnhancedResume = structured_llm.invoke(prompt)
        
        if "summary" not in r:
            r["summary"] = {}
        r["summary"]["content"] = enhanced.summary_content
        
        for i, exp in enumerate(r.get("experience", [])):
            if i < len(enhanced.experience):
                exp["highlights"] = honest_highlights(
                    exp.get("highlights") or [], enhanced.experience[i].highlights
                )

        for i, proj in enumerate(r.get("projects", [])):
            if i < len(enhanced.projects):
                proj["highlights"] = honest_highlights(
                    proj.get("highlights") or [], enhanced.projects[i].highlights
                )

        r["skills"] = regrouped(r.get("skills") or [], enhanced.skills)

        polished = Resume.model_validate(r).model_dump()

        if onto_tailored:
                                                                                       
            generated["tailored"] = polished
            return {"generated_resumes": generated, "phase": "enhancing"}

        return {"master_profile": polished, "phase": "enhancing"}
    except Exception as e:
        logger.error(f"Failed to enhance resume: {e}")
        return {"phase": "enhancing"}

if __name__ == "__main__":
                                                                                     
    original = "Reduced latency from 8-10s to 3-6s using Redis caching."
    assert keep_honest(original, "Cut latency from 8-10s to 3-6s via Redis.")\
        == "Cut latency from 8-10s to 3-6s via Redis."
    assert keep_honest(original, "Cut latency by 40% using Redis.") == original, "40% was never said"

    assert keep_honest(original, "Cut latency substantially using Redis.")\
        == "Cut latency substantially using Redis."

    assert keep_honest("Saved $1,000 annually", "Saved 1000 dollars a year") == "Saved 1000 dollars a year"
    assert keep_honest("Built on OAuth 2.0", "Implemented OAuth 2.0") == "Implemented OAuth 2.0"

    plain = "Orchestrated TTS, AWS S3, and SSE for real-time audio streaming."
    assert keep_honest(plain, "Orchestrated TTS, AWS S3, and SSE, cutting latency 60%.") == plain
    assert numbers_in(plain) == {"3"}, "S3 counts, and the source has it too"

    originals = ["Shipped the parser", "Ran the migration", "Owned the deploy"]
    polished = ["Built the parser", "Led the migration", "Drove the deploy"]
    assert honest_highlights(originals, polished) == polished
    assert honest_highlights(originals, ["Built the parser", "Cut it 40%", "Drove the deploy"])\
        == ["Built the parser", "Ran the migration", "Drove the deploy"]

    shredded = ["Engineered a RAG platform", "FAISS", "Redis", "SSE) enabling Q&A over documents (PDF",
                "Word", "Excel", "CSV) and media", "Integrated Deepgram for transcription"]
    condensed = ["Engineered a multimodal RAG platform over FAISS, Redis and SSE",
                 "Integrated Deepgram for timestamped transcription"]
    assert honest_highlights(shredded, condensed) == condensed, "fragments must not come back"

    nine = [f"Bullet {chr(97 + i)}" for i in range(9)]
    assert honest_highlights(shredded, nine) == nine[:MAX_BULLETS], "strongest first, then stop"
    assert len(honest_highlights([f"Old {chr(97 + i)}" for i in range(9)], [])) == MAX_BULLETS

    moved = ["Ran the deploy", "Cut build time 40%"]
    assert honest_highlights(moved, ["Cut build time 40% by rebuilding the deploy"])\
        == ["Cut build time 40% by rebuilding the deploy"]
                                                                           
    assert honest_highlights(moved, ["Cut build time 90%"]) == moved[:MAX_BULLETS],\
        "nothing survived the check, so the raw bullets stand"

    assert honest_highlights([], []) == []
    assert honest_highlights(originals, []) == originals, "a failed rewrite loses nothing"

    ONE_BUCKET = [{"name": "Core Skills", "keywords": ["JavaScript", "Python", "React", "MongoDB"]}]
    filed = regrouped(ONE_BUCKET, [
        SkillGroup(name="Languages", keywords=["JavaScript", "Python"]),
        SkillGroup(name="Frontend", keywords=["React"]),
        SkillGroup(name="Databases", keywords=["MongoDB"]),
    ])
    assert [g["name"] for g in filed] == ["Languages", "Frontend", "Databases"], filed
    assert filed[0]["keywords"] == ["JavaScript", "Python"]

    assert regrouped(ONE_BUCKET, [SkillGroup(name="Languages", keywords=["JavaScript", "Python"])])\
        == ONE_BUCKET, "a dropped skill discards the whole regrouping"
    assert regrouped(ONE_BUCKET, [
        SkillGroup(name="Languages", keywords=["JavaScript", "Python", "React", "MongoDB", "Rust"])
    ]) == ONE_BUCKET, "an invented skill discards the whole regrouping"

    assert regrouped(ONE_BUCKET, []) == ONE_BUCKET
    assert regrouped([], []) == []
                                                   
    assert regrouped(ONE_BUCKET, [
        SkillGroup(name="Languages", keywords=["JavaScript", "Python", "React", "MongoDB"]),
        SkillGroup(name="Tools", keywords=[]),
    ]) == [{"name": "Languages", "keywords": ["JavaScript", "Python", "React", "MongoDB"]}]

    print("enhance_resume ok")
