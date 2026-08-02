"""The interview's planner: what is the highest-value question to ask next?"""

import json
import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.graphs.node.analyze_gaps import KIND_RANK
from app.graphs.node.generate_question import current_item
from app.graphs.state import ResumeState
from app.utils.llm import get_openai_llm
from app.graphs.prompts import MAY_FOLLOW_UP, NO_FOLLOW_UP, TURN_PLAN
from app.utils.prompt import as_dict, compact

logger = logging.getLogger(__name__)

MAX_EXCHANGES = 6

MAX_PROBE_DEPTH = 2
MAX_FOLLOW_UPS = 6

UNSURE_BELOW = 0.9

class FollowUp(BaseModel):
    field: str = Field(
        description="Path of the item the follow-up is about, copied exactly from the profile or the "
        "waiting list — e.g. 'experience[0]', 'basics'. Never a path that does not already exist."
    )
    fields: List[str] = Field(
        description="The resume field names the answer will be stored under, e.g. ['end_date'] or "
        "['highlights']. They must be real fields of that item, or the answer has nowhere to go."
    )
    question: str = Field(
        description="The question to put to the user, one or two sentences. Quote their own words "
        "back when you are resolving a contradiction or confirming something you are unsure of."
    )
    why: Literal["incomplete", "contradiction", "unsure", "thin"] = Field(
        description="Which of reasons a/b/c/d you are asking for: 'incomplete' (a), "
        "'contradiction' (b), 'unsure' (c), 'thin' (d)."
    )

class TurnPlan(BaseModel):
    follow_up: Optional[FollowUp] = Field(
        default=None,
        description="Set ONLY when the most recent answer was incomplete, ambiguous, contradicts "
        "something already recorded, landed with low confidence, or answered something substantial "
        "so thinly that one more question would materially improve the resume. Otherwise null.",
    )
    next_field: str = Field(
        default="",
        description="The `field` of the waiting question worth asking next, copied exactly. "
        "Empty to keep the existing order.",
    )
    drop_sections: List[str] = Field(
        default_factory=list,
        description="Sections not worth asking about any more, because what is already recorded "
        "covers them. Naming every remaining optional section is how you end the interview early.",
    )
    why: str = Field(default="", description="One short sentence on why, for the log.")

def unjudged(state: ResumeState) -> List[Dict[str, Any]]:
    """Exchanges this node has not already acted on."""
    return [e for e in (state.get("exchanges") or []) if not e.get("judged")]

def mark_judged(state: ResumeState) -> Dict[str, Any]:
    """Retire the pending exchanges, keeping them as context for later turns."""
    history = state.get("exchanges") or []
    if not any(not e.get("judged") for e in history):
        return {}
    return {"exchanges": [{**e, "judged": True} for e in history]}

def candidates(queue: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The gaps the planner may legally put first."""
    head = queue[0]
    if head.get("is_gate"):
        return [head]

    rank = KIND_RANK.get(head.get("kind"), 1)
    return [
        gap for gap in queue
        if gap.get("section") == head.get("section")
        and not gap.get("is_gate")
        and KIND_RANK.get(gap.get("kind"), 1) == rank
    ]

def droppable(named: List[str], queue: List[Dict[str, Any]]) -> set:
    """Of the sections the planner wants to drop, the ones it is allowed to."""
    required = {g.get("section") for g in queue if g.get("kind") == "required"}
    queued = {g.get("section") for g in queue}
    return {s for s in named if s and s in queued and s not in required}

def promote(queue: List[Dict[str, Any]], field: str) -> List[Dict[str, Any]]:
    """Move `field` to the head of the queue, keeping everything else in order."""
    chosen = next(g for g in queue if g.get("field") == field)
    return [chosen] + [g for g in queue if g is not chosen]

def probe_depth(state: ResumeState, field: str) -> int:
    """How many questions this node has already invented about one item."""
    return sum(
        1 for e in (state.get("exchanges") or [])
        if e.get("follow_up") and e.get("field") == field
    )

def worth_probing(follow_up: Optional[FollowUp], pending: List[Dict[str, Any]]) -> bool:
    """Stop when the answer was already good enough."""
    if not follow_up or not pending:
        return False

    if follow_up.why == "contradiction":
        return True

    return any(e.get("sufficiency", "sufficient") != "sufficient" for e in pending)

def usable_follow_up(
    follow_up: Optional[FollowUp],
    state: ResumeState,
    queue: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Turn the planner's follow-up into a queue item, or throw it away."""
    if not follow_up or not follow_up.question.strip() or not follow_up.fields:
        return None

    asked = state.get("follow_ups_asked") or 0
    if asked >= MAX_FOLLOW_UPS:
        logger.info("Follow-up budget spent (%d); moving on instead.", asked)
        return None

    depth = probe_depth(state, follow_up.field)
    if depth >= MAX_PROBE_DEPTH:
        logger.info("Already probed %s %d time(s); that is deep enough.", follow_up.field, depth)
        return None

    known = {g.get("field") for g in queue}
    if follow_up.field not in known and not current_item(as_dict(state.get("master_profile")), follow_up.field):
        logger.warning("Follow-up named an item that does not exist: %r", follow_up.field)
        return None

    return {
        "field": follow_up.field,

        "section": follow_up.field.partition("[")[0],
        "kind": "follow_up",
        "missing_fields": list(follow_up.fields),
        "is_gate": False,
        "question_text": follow_up.question.strip(),
        "reason": "Following up on the previous answer.",
    }

def transcript(history: List[Dict[str, Any]]) -> str:
    """The interview so far, as the planner reads it."""
    if not history:
        return "Nothing yet — this is the first question of the session."

    lines = []
    for exchange in history:
        tag = " [a follow-up you asked]" if exchange.get("follow_up") else ""
        state_tag = "" if exchange.get("judged") else "  <-- MOST RECENT, not yet acted on"
        lines.append(f"Q{tag}: {exchange.get('question')}")
        lines.append(f"A: {exchange.get('answer')}{state_tag}")

        recorded = json.dumps(exchange.get("values") or {}, ensure_ascii=False)
        unsure = {f: c for f, c in (exchange.get("confidence") or {}).items() if c < UNSURE_BELOW}
        note = f"  (only {int(min(unsure.values()) * 100)}% sure of {', '.join(unsure)})" if unsure else ""
        lines.append(f"   recorded: {recorded}{note}")

        if exchange.get("sufficiency", "sufficient") != "sufficient":
            lines.append(f"   rated {exchange['sufficiency']}: {exchange.get('gap') or 'vague'}")

    return "\n".join(lines)

def _plan(state: ResumeState, queue: List[Dict[str, Any]], may_follow_up: bool) -> Optional[TurnPlan]:
    waiting = "\n".join(
        f"- {g.get('field')} (priority {g.get('kind')}, section {g.get('section')}): {g.get('reason', '')}"
        for g in queue
    )

    prompt = TURN_PLAN.format(
        completion=state.get("completion") or 0,
        resume=compact(state.get("master_profile")),
        transcript=transcript(state.get("exchanges") or []),
        waiting=waiting,
        skipped=state.get("skipped") or "nothing",
        follow_up_rule=MAY_FOLLOW_UP if may_follow_up else NO_FOLLOW_UP,
    )

    try:
        return get_openai_llm().with_structured_output(
            TurnPlan, method="function_calling"
        ).invoke(prompt)
    except Exception as e:

        logger.error("Conversation planner failed, falling back to queue order: %r", e)
        return None

def conversation_planner(state: ResumeState) -> Dict[str, Any]:
    """Choose the next question. Writes `active_target`, and the queue it came from."""
    queue = list(state.get("question_queue") or [])
    done: Dict[str, Any] = mark_judged(state)

    if not queue:
        return {**done, "active_target": None}

    if state.get("validation_errors"):

        return {**done, "active_target": queue[0]}

    pending = unjudged(state)
    if not pending and len(candidates(queue)) < 2:

        return {**done, "active_target": queue[0]}

    plan = _plan(state, queue, may_follow_up=bool(pending))
    if plan is None:
        return {**done, "active_target": queue[0]}

    logger.info("Planner: next=%r drop=%s follow_up=%s — %s",
                plan.next_field, plan.drop_sections, bool(plan.follow_up), plan.why)

    updates: Dict[str, Any] = dict(done)

    dropped = droppable(plan.drop_sections, queue)
    if dropped:
        logger.info("Planner dropped section(s): %s", ", ".join(sorted(dropped)))
        queue = [g for g in queue if g.get("section") not in dropped]
        updates["skipped"] = list(state.get("skipped") or []) + sorted(dropped)
        updates["question_queue"] = queue
        if not queue:
            return {**updates, "active_target": None}

    follow_up = (usable_follow_up(plan.follow_up, state, queue)
                 if worth_probing(plan.follow_up, pending) else None)
    if follow_up:
        updates["question_queue"] = [follow_up] + queue
        updates["follow_ups_asked"] = (state.get("follow_ups_asked") or 0) + 1
        return {**updates, "active_target": follow_up}

    allowed = {g.get("field") for g in candidates(queue)}
    if plan.next_field in allowed and plan.next_field != queue[0].get("field"):
        queue = promote(queue, plan.next_field)
        updates["question_queue"] = queue
    elif plan.next_field and plan.next_field != queue[0].get("field"):
        logger.info("Planner picked %r, which it may not reorder to; keeping queue order.",
                    plan.next_field)

    return {**updates, "active_target": queue[0]}
