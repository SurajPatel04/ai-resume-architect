"""Deterministic profile mutation.

Shared by validate_entities (dry-run against the schema) and merge_profile (for real)
so the two can never drift apart.
"""

import copy
import re
from typing import Any, Dict, List, Optional

LIST_FIELDS = {"highlights", "keywords"}

_MARKER = re.compile(r"^\s*(?:[-*•‣▪·]\s*|\d+[.)]\s+)")

def split_list(key: str, text: str) -> List[str]:
    """One free-text answer into the list items it holds.

    Bullets are separated by newlines, never by commas. Splitting them on commas is what
    turned one pasted project into "FAISS", "Redis", "SSE) enabling Q&A over documents
    (PDF", "Word", "Excel" — a real bullet names its stack in a comma list and cannot
    survive being split on one. Skills are the opposite: a comma list is the whole point
    of "Python, Go, Rust", and they arrive on a single line.
    """
    if key == "highlights":
        parts = text.replace("\\n", "\n").splitlines()
    else:
        parts = text.replace("\\n", ",").replace("\n", ",").split(",")

    return [item for item in (_MARKER.sub("", p).strip() for p in parts) if item]

def impact_key(field: str, bullet_index: Optional[int]) -> str:
    """Stable id for 'we already asked this bullet for a number'.

    Written by validate/merge into `skipped`, read back by analyze_gaps. One
    definition so the writer and the reader can't disagree on the format.
    """
    return f"impact.{field}.{bullet_index}"

def _resolve(r: Dict[str, Any], target_field: str) -> Any:
    """Walk 'experience[0]' / 'basics' / 'skills' to its container, creating what's missing."""
    current: Any = r
    for part in target_field.split("."):
        if "[" in part and "]" in part:
            list_name, index_str = part.replace("]", "").split("[")
            index = int(index_str)
            if not isinstance(current.get(list_name), list):
                current[list_name] = []
            while len(current[list_name]) <= index:
                current[list_name].append({})
            current = current[list_name][index]
        else:
            if current.get(part) is None:
                current[part] = {}
            current = current[part]
    return current

def apply_extraction(
    resume: Dict[str, Any],
    target_field: str,
    values: Dict[str, Any],
    bullet_index: Optional[int] = None,
    replace: bool = False,
) -> Dict[str, Any]:
    """Return a NEW resume dict with `values` applied at `target_field`.

    bullet_index set => the user just quantified an existing bullet. Fold the number
    into that bullet instead of appending a new one; enhance_resume rewrites it into
    proper prose at the end of the run.

    replace => overwrite list fields instead of appending to them. Collecting an answer
    adds to what's there; correcting a bad import must not.
    """
    r = copy.deepcopy(resume)
    current = _resolve(r, target_field)

    if not isinstance(current, (dict, list)) and "." in target_field:
        target_field, leaf = target_field.rsplit(".", 1)
        current = _resolve(r, target_field)
        values = {leaf: next(iter(values.values()))} if values else {}

    if bullet_index is not None:
        highlights = current.get("highlights") or []
        metric = " ".join(str(v).strip() for v in values.values() if str(v).strip())
        if metric and 0 <= bullet_index < len(highlights):
            highlights[bullet_index] = f"{highlights[bullet_index]} ({metric})"
            current["highlights"] = highlights
        return r

    if target_field == "skills":
        new_skills = values.get("skills")
        if isinstance(new_skills, str):
            new_skills = [s.strip() for s in new_skills.split(",") if s.strip()]
        if new_skills:
            if current:
                current[0]["keywords"] = current[0].get("keywords", []) + list(new_skills)
            else:
                current.append({"name": "Core Skills", "keywords": list(new_skills)})
        return r

    for key, val in values.items():
        existing = current.get(key)
        if isinstance(existing, list) or key in LIST_FIELDS:
            if replace or not isinstance(existing, list):
                existing = []
                current[key] = existing
            if isinstance(val, list):
                existing.extend(val)
            elif isinstance(val, str):
                existing.extend(split_list(key, val))
            else:
                existing.append(val)
        else:
            current[key] = val
    return r

if __name__ == "__main__":
    base = {"basics": {"name": "", "email": ""}, "experience": [], "skills": [], "projects": []}

    r = apply_extraction(base, "basics", {"name": "Priya", "email": "p@x.com"})
    assert r["basics"] == {"name": "Priya", "email": "p@x.com"}, r["basics"]

    r = apply_extraction(base, "experience[0]", {"company": "Acme", "highlights": "Shipped X\nRan Y"})
    assert r["experience"][0]["company"] == "Acme"
    assert r["experience"][0]["highlights"] == ["Shipped X", "Ran Y"], r["experience"][0]

    PASTED = (
        "• Engineered a full-stack multimodal RAG platform (FastAPI, LangGraph, React, "
        "MongoDB, FAISS, Redis, SSE) enabling Q&A over documents (PDF, Word, Excel, CSV).\n"
        "• Integrated Deepgram for timestamped transcription, enabling precise retrieval.\n"
    )
    kept = apply_extraction(base, "projects[0]", {"highlights": PASTED})["projects"][0]["highlights"]
    assert len(kept) == 2, kept
    assert kept[0].startswith("Engineered"), "the marker is stripped, the sentence is not"
    assert "FastAPI, LangGraph, React" in kept[0], "a bullet's own comma list must survive"
    assert not any(k in ("FAISS", "Redis", "Word", "Excel") for k in kept), kept

    assert split_list("highlights", "- One\n\n* Two\n1. Three\n•Four")\
        == ["One", "Two", "Three", "Four"]
                                                                               
    assert split_list("keywords", "Python, Go, Rust") == ["Python", "Go", "Rust"]
    assert split_list("keywords", "Python\nGo") == ["Python", "Go"], "newlines still separate"
    assert split_list("highlights", "   ") == [] and split_list("keywords", "") == []

    r = apply_extraction({"skills": [{"name": "Languages", "keywords": ["Python"]}]}, "skills", {"skills": ["Go"]})
    assert r["skills"][0]["keywords"] == ["Python", "Go"], r["skills"]

    prof = {"experience": [{"highlights": ["Old bullet"]}]}
    assert apply_extraction(prof, "experience[0]", {"highlights": "New"})["experience"][0]["highlights"]\
        == ["Old bullet", "New"]
    assert apply_extraction(prof, "experience[0]", {"highlights": "New"}, replace=True)["experience"][0]["highlights"]\
        == ["New"]

    prof = {"experience": [{"highlights": ["Managed social media", "Ran ads"]}]}
    r = apply_extraction(prof, "experience[0]", {"metric": "grew engagement 150%"}, bullet_index=0)
    assert r["experience"][0]["highlights"][0] == "Managed social media (grew engagement 150%)"
    assert r["experience"][0]["highlights"][1] == "Ran ads"
    assert prof["experience"][0]["highlights"][0] == "Managed social media", "must not mutate the input"

    prof = {"basics": {"name": "S", "phone": "9876543210"}}
    assert apply_extraction(prof, "basics.phone", {"phone": "9839916634"})["basics"]\
        == {"name": "S", "phone": "9839916634"}
    assert apply_extraction(prof, "basics.phone", {"value": "9839916634"})["basics"]["phone"] == "9839916634"
    assert apply_extraction({"summary": {"content": "old"}}, "summary.content", {"content": "new"})["summary"]\
        == {"content": "new"}
    assert apply_extraction({"experience": [{"company": "Acme"}]}, "experience[0].company", {"company": "Zeta"})\
        ["experience"][0]["company"] == "Zeta"

    print("apply_extraction ok")