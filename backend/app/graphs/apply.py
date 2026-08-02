"""Deterministic profile mutation."""

import copy
import re
from typing import Any, Dict, List, Optional

LIST_FIELDS = {"highlights", "keywords"}

_MARKER = re.compile(r"^\s*(?:[-*•‣▪·]\s*|\d+[.)]\s+)")

def split_list(key: str, text: str) -> List[str]:
    """One free-text answer into the list items it holds."""
    if key == "highlights":
        parts = text.replace("\\n", "\n").splitlines()
    else:
        parts = text.replace("\\n", ",").replace("\n", ",").split(",")

    return [item for item in (_MARKER.sub("", p).strip() for p in parts) if item]

SLOT = "{}"

def slot_parts(template: str) -> Optional[List[str]]:
    """A bullet template split around its one blank, or None if it isn't one."""
    if not template or template.count(SLOT) != 1:
        return None

    before, after = template.split(SLOT)
    if any(brace in before + after for brace in "{}"):
        return None

    return [before, after]

def fill_slot(template: str, figure: str) -> Optional[str]:
    """The bullet with the candidate's figure in the blank."""
    parts = slot_parts(template)
    figure = (figure or "").strip()
    if parts is None or not figure:
        return None
    return f"{parts[0]}{figure}{parts[1]}"

def read_slot(template: str, answer: str) -> Optional[str]:
    """The figure out of a bullet the user has already filled in, or None."""
    parts = slot_parts(template)
    if parts is None:
        return None

    before, after = parts
    answer = (answer or "").strip()
    if not answer.startswith(before) or not answer.endswith(after):
        return None

    figure = answer[len(before):len(answer) - len(after)] if after else answer[len(before):]
    return figure.strip() or None

def impact_key(field: str, bullet_index: Optional[int]) -> str:
    """Stable id for 'we already asked this bullet for a number'."""
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
    template: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a NEW resume dict with `values` applied at `target_field`."""
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
            rewritten = fill_slot(template, metric) if template else None
            highlights[bullet_index] = rewritten or f"{highlights[bullet_index]} ({metric})"
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
