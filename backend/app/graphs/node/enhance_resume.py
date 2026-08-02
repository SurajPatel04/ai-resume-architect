import logging
import re
from typing import Any, Dict, List

from app.graphs.state import ResumeState, Resume
from app.utils.llm import get_openai_llm
from app.graphs.prompts import ENHANCE
from app.utils.prompt import compact
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_NUMBER = re.compile(r"\d+(?:\.\d+)?")

MAX_BULLETS = 4

def numbers_in(text: str) -> set:
    """Every figure in a bullet. Commas stripped so 1,000 and 1000 are the same number."""
    return set(_NUMBER.findall((text or "").replace(",", "")))

def keep_honest(original: str, rewritten: str) -> str:
    """Discard a rewrite that introduces a figure the original never had."""
    if numbers_in(rewritten) <= numbers_in(original):
        return rewritten
    logger.warning("Dropped a rewrite that invented a figure: %r", rewritten)
    return original

def honest_highlights(originals: List[str], rewritten: List[str]) -> List[str]:
    """The polished bullets, minus anything that invented a figure, capped at MAX_BULLETS.
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
    company: str = Field(
        default="",
        description="The employer this entry is about, copied exactly from the input, so its "
        "highlights can be matched back to the right job.",
    )
    highlights: List[str] = Field(
        description=f"At most {MAX_BULLETS} polished highlights for this experience, strongest first."
    )

class EnhancedProject(BaseModel):
    name: str = Field(
        default="",
        description="The project's name, copied exactly from the input, so its highlights can be "
        "matched back to the right project.",
    )
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

def aligned(originals: List[dict], rewrites: List[Any], key: str) -> List[Any]:
    """Each entry paired with the rewrite that NAMES it, not the one in its slot.

    The prompt asks for the entries back in the order they were given. When that holds,
    position works. When it does not — and it does not reliably — one project's polished
    bullets land on another project, which is how an interview platform ended up
    described as a video renderer.

    Matched on the identifier the model echoes back. Position is the fallback, and only
    when the counts agree: a different number of entries means the pairing is already
    guesswork and the originals are the safer answer.
    """
    by_name: Dict[str, Any] = {}
    for rewrite in rewrites or []:
        name = str(getattr(rewrite, key, "") or "").strip().casefold()
        if name:
            by_name.setdefault(name, rewrite)

    out: List[Any] = []
    for index, entry in enumerate(originals or []):
        name = str(entry.get(key) or "").strip().casefold()
        match = by_name.get(name)
        if match is None and len(rewrites or []) == len(originals or []):
            match = rewrites[index]
        if match is None:
            logger.warning("No rewrite could be matched to %s %r; keeping it as written.",
                           key, entry.get(key))
        out.append(match)
    return out

def regrouped(original: List[dict], groups: List[SkillGroup]) -> List[dict]:
    """The regrouped skills, or the originals if a single one was invented or lost."""
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
    """Polishes the resume's bullets and summary for maximum impact using the LLM. Scoping the
    output to prevent hallucinated data loss of factual fields.
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

    try:
        enhanced: EnhancedResume = structured_llm.invoke(
            ENHANCE.format(max_bullets=MAX_BULLETS, resume=compact(r))
        )

        if "summary" not in r:
            r["summary"] = {}
        r["summary"]["content"] = enhanced.summary_content

        jobs = r.get("experience", [])
        for exp, match in zip(jobs, aligned(jobs, enhanced.experience, "company")):
            if match is not None:
                exp["highlights"] = honest_highlights(exp.get("highlights") or [], match.highlights)

        works = r.get("projects", [])
        for proj, match in zip(works, aligned(works, enhanced.projects, "name")):
            if match is not None:
                proj["highlights"] = honest_highlights(proj.get("highlights") or [], match.highlights)

        r["skills"] = regrouped(r.get("skills") or [], enhanced.skills)

        polished = Resume.model_validate(r).model_dump()

        if onto_tailored:

            generated["tailored"] = polished
            return {"generated_resumes": generated, "phase": "enhancing"}

        return {"master_profile": polished, "phase": "enhancing"}
    except Exception as e:
        logger.error(f"Failed to enhance resume: {e}")
        return {"phase": "enhancing"}
