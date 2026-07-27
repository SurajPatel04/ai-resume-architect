"""Structured LLM responses used by the resume interview.

Section extraction responses deliberately contain the actual Resume models.  Keeping
these schemas in one module makes the LLM contract explicit and avoids translating a
typed result through generic ``{field, value}`` rows before it reaches the profile.
"""

import copy
import json
import re
from typing import Any, Dict, List, Literal, Type

from pydantic import BaseModel, Field

from app.graphs.state import Basics, Certification, Education, Experience, Project, SkillCategory, Summary

class Judgement(BaseModel):
    is_skip: bool = Field(description="True when the user explicitly declined or has no information.")
    sufficiency: Literal["unusable", "thin", "sufficient"] = "sufficient"
    gap: str = ""

class FieldConfidence(BaseModel):
    """A confidence score for one field on one extracted item."""

    item: int = Field(default=0, ge=0, description="Zero-based index in items.")
    field: str = Field(description="Field name on that item's Resume model.")
    confidence: float = Field(ge=0.0, le=1.0)

class BasicsExtraction(Judgement):
    items: List[Basics] = Field(default_factory=list)
    confidence: List[FieldConfidence] = Field(default_factory=list)

class SummaryExtraction(Judgement):
    items: List[Summary] = Field(default_factory=list)
    confidence: List[FieldConfidence] = Field(default_factory=list)

class ExperienceExtraction(Judgement):
    items: List[Experience] = Field(default_factory=list)
    confidence: List[FieldConfidence] = Field(default_factory=list)

class EducationExtraction(Judgement):
    items: List[Education] = Field(default_factory=list)
    confidence: List[FieldConfidence] = Field(default_factory=list)

class ProjectExtraction(Judgement):
    items: List[Project] = Field(default_factory=list)
    confidence: List[FieldConfidence] = Field(default_factory=list)

class CertificationExtraction(Judgement):
    items: List[Certification] = Field(default_factory=list)
    confidence: List[FieldConfidence] = Field(default_factory=list)

class SkillsExtraction(Judgement):
    """Named skill groups, e.g. ``Languages: Python, TypeScript``."""

    items: List[SkillCategory] = Field(default_factory=list)
    confidence: List[FieldConfidence] = Field(default_factory=list)

SECTION_EXTRACTION_SCHEMAS: Dict[str, Type[BaseModel]] = {
    "basics": BasicsExtraction,
    "summary": SummaryExtraction,
    "experience": ExperienceExtraction,
    "education": EducationExtraction,
    "projects": ProjectExtraction,
    "certifications": CertificationExtraction,
    "skills": SkillsExtraction,
}

class MetricExtraction(Judgement):
    metric: str = ""

class FreeformEntity(BaseModel):
    """Fallback only for planner fields that have no Resume model."""

    field: str
    value: Any
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    item: int = Field(default=0, ge=0)

class FreeformExtraction(Judgement):
    entities: List[FreeformEntity] = Field(default_factory=list)

def provided_values(item: Dict[str, Any]) -> Dict[str, Any]:
    """Remove model defaults so a partial answer never erases existing resume data."""
    return {key: value for key, value in item.items() if value not in ("", None, [], {})}

LIST_ITEM_SECTIONS = {"experience", "education", "projects", "certifications", "skills"}

def merge_typed_items(resume: Dict[str, Any], section: str, target: str,
                      items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge typed extraction items directly into a resume dictionary.

    The first item fills the entry the question targeted; subsequent items are appended.
    No generic entity rows or field/value reconstruction are involved.
    """
    payloads = [provided_values(item) for item in items]
    payloads = [item for item in payloads if item]
    if not payloads:
        return copy.deepcopy(resume)

    merged = copy.deepcopy(resume)
    if section not in LIST_ITEM_SECTIONS:
        current = dict(merged.get(section) or {})
        current.update(payloads[0])
        merged[section] = current
        return merged

    entries = list(merged.get(section) or [])
    if section == "skills":
                                                                                       
        by_name = {(entry.get("name") or "").strip().lower(): entry for entry in entries}
        for payload in payloads:
            name = payload.get("name", "").strip()
            if not name:
                continue
            target_entry = by_name.get(name.lower())
            if target_entry is None:
                target_entry = {"name": name, "keywords": []}
                entries.append(target_entry)
                by_name[name.lower()] = target_entry
            existing = target_entry.setdefault("keywords", [])
            existing_lower = {str(value).lower() for value in existing}
            for keyword in payload.get("keywords") or []:
                if keyword.lower() not in existing_lower:
                    existing.append(keyword)
                    existing_lower.add(keyword.lower())
        merged[section] = entries
        return merged
    match = re.search(r"\[(\d+)\]", target)
    index = int(match.group(1)) if match else len(entries)
    while len(entries) <= index:
        entries.append({})

    first = dict(entries[index])
    for key, value in payloads[0].items():
        if isinstance(first.get(key), list) and isinstance(value, list):
                                                                                   
            existing = list(first[key])
            seen = {str(item).strip().casefold() for item in existing}
            for item in value:
                normalized = str(item).strip().casefold()
                if normalized and normalized not in seen:
                    existing.append(item)
                    seen.add(normalized)
            first[key] = existing
        else:
            first[key] = value
    entries[index] = first
    entries.extend(payloads[1:])
                                                                                    
    unique_entries = []
    fingerprints = set()
    for entry in entries:
        fingerprint = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        if fingerprint not in fingerprints:
            unique_entries.append(entry)
            fingerprints.add(fingerprint)
    entries = unique_entries
    merged[section] = entries
    return merged