"""How resume data is written into a prompt."""

import json
from typing import Any, Dict

EMPTY = ("", [], {}, None)

def as_dict(resume: Any) -> Dict[str, Any]:
    """The profile as a plain dict, whether it arrives as a model or already merged."""
    return resume.model_dump() if hasattr(resume, "model_dump") else (resume or {})

def prune(value: Any) -> Any:
    """The same structure with every empty field dropped, and every list the same length."""
    if isinstance(value, dict):
        kept = ((key, prune(item)) for key, item in value.items())
        return {key: item for key, item in kept if item not in EMPTY}
    if isinstance(value, list):
        return [prune(item) for item in value]
    return value

def compact(resume: Any) -> str:
    """A profile as it should appear inside a prompt: pruned, JSON, no filler space."""
    return json.dumps(prune(as_dict(resume)), ensure_ascii=False, separators=(",", ":"))
