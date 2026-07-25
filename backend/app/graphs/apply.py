"""Deterministic profile mutation.

Shared by validate_entities (dry-run against the schema) and merge_profile (for real)
so the two can never drift apart.
"""

import copy
from typing import Any, Dict, Optional

                                                                      
                                                                                 
                                                                   
LIST_FIELDS = {"highlights", "keywords"}


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
                existing.extend(v.strip() for v in val.replace("\\n", ",").replace("\n", ",").split(",") if v.strip())
            else:
                existing.append(val)
        else:
            current[key] = val
    return r


if __name__ == "__main__":
    base = {"basics": {"name": "", "email": ""}, "experience": [], "skills": [], "projects": []}

                                          
    r = apply_extraction(base, "basics", {"name": "Priya", "email": "p@x.com"})
    assert r["basics"] == {"name": "Priya", "email": "p@x.com"}, r["basics"]

                                                                            
    r = apply_extraction(base, "experience[0]", {"company": "Acme", "highlights": "Shipped X, Ran Y"})
    assert r["experience"][0]["company"] == "Acme"
    assert r["experience"][0]["highlights"] == ["Shipped X", "Ran Y"], r["experience"][0]

                                                                    
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

    print("apply_extraction ok")