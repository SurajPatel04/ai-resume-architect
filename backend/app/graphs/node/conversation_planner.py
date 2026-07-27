"""The interview's planner: what is the highest-value question to ask next?

analyze_gaps answers "what is empty" — a set of facts about missing fields. This node
answers the questions emptiness cannot:

  - Did the last answer actually answer what was asked, or only half of it?
  - Does it contradict something already recorded, or did it land with low confidence?
  - How deep is this worth probing, given how substantial the answer was?
  - Is the next queued gap still worth a turn, or is the resume already good enough?
  - Of everything left, which single question yields the most?

It reads the running transcript, not just the last reply — half of "was that answer
complete" is what has already been asked and how it was answered. It picks from the
queue analyze_gaps built, may push ONE targeted follow-up in front of it, and may give
up on optional sections to end the interview early.

It never invents a question with nowhere to land: a follow-up names a field path that
already exists, so extract_entities and merge_profile store the reply where the rest of
the graph expects to find it.

The deterministic order is not up for renegotiation. A gate opens a whole section and
rebuilds the queue behind it, a nice-to-have must never displace a field the resume
cannot be rendered without, and no question may leave a section half-finished — so the
planner only ever chooses between equals, inside the section already on the table.
"""

import json
import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.graphs.node.analyze_gaps import KIND_RANK
from app.graphs.node.generate_question import current_item
from app.graphs.state import ResumeState
from app.utils.llm import get_openai_llm

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

def _as_dict(resume: Any) -> Dict[str, Any]:
    return resume.model_dump() if hasattr(resume, "model_dump") else (resume or {})

def unjudged(state: ResumeState) -> List[Dict[str, Any]]:
    """Exchanges this node has not already acted on.

    Not every turn reaches merge_profile — a gate tap and an abandoned question both
    resolve elsewhere — so "the last exchange" and "an exchange I have not seen" are
    different questions. Judging the same answer twice is what produces a follow-up
    about something the user settled two turns ago.
    """
    return [e for e in (state.get("exchanges") or []) if not e.get("judged")]

def mark_judged(state: ResumeState) -> Dict[str, Any]:
    """Retire the pending exchanges, keeping them as context for later turns."""
    history = state.get("exchanges") or []
    if not any(not e.get("judged") for e in history):
        return {}
    return {"exchanges": [{**e, "judged": True} for e in history]}

def candidates(queue: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The gaps the planner may legally put first.

    Never leaves the section on the table. analyze_gaps orders the queue section by
    section, and a question that jumps out of a half-finished one — a LinkedIn URL in
    the middle of education, then back — reads as having lost the thread, however
    individually valuable it was. Finishing the topic is the higher-value move.

    A gate is untouchable on top of that: career_level is the reason every later section
    is ordered the way it is, and answering one clears the queue for a rebuild. Within
    what remains, only gaps of equal priority swap, so a nice-to-have can never displace
    a field the resume cannot be rendered without.
    """
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
    """Of the sections the planner wants to drop, the ones it is allowed to.

    A section still holding a required gap is not one of them, whatever the model thinks —
    a resume with no name on it is not a resume. Everything else is fair game, and naming
    all of them is how the planner decides the resume is already good enough.
    """
    required = {g.get("section") for g in queue if g.get("kind") == "required"}
    queued = {g.get("section") for g in queue}
    return {s for s in named if s and s in queued and s not in required}

def promote(queue: List[Dict[str, Any]], field: str) -> List[Dict[str, Any]]:
    """Move `field` to the head of the queue, keeping everything else in order.

    active_target has to BE the head. merge_profile and validate_entities both advance
    by popping queue[0], so a target sitting anywhere else pops somebody else's gap and
    silently loses the question that was actually just answered.
    """
    chosen = next(g for g in queue if g.get("field") == field)
    return [chosen] + [g for g in queue if g is not chosen]

def probe_depth(state: ResumeState, field: str) -> int:
    """How many questions this node has already invented about one item.

    The global budget alone cannot tell "probed one project properly" from "asked six
    different things once", and depth is exactly the difference a recruiter would draw.
    """
    return sum(
        1 for e in (state.get("exchanges") or [])
        if e.get("follow_up") and e.get("field") == field
    )

def worth_probing(follow_up: Optional[FollowUp], pending: List[Dict[str, Any]]) -> bool:
    """Stop when the answer was already good enough.

    How deep to go is a property of the answer, not of how interesting the model finds
    the topic — so the extractor's own rating decides it, and a "sufficient" answer ends
    the thread. The single exception is a contradiction: a complete, well-formed answer
    that disagrees with something recorded is precisely the case worth re-opening.
    """
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
    """Turn the planner's follow-up into a queue item, or throw it away.

    Resolved back against the real profile for the same reason review_quality resolves
    its bullet picks: an invented path produces a question whose answer merge_profile
    would write into a section that does not exist.
    """
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
    if follow_up.field not in known and not current_item(_as_dict(state.get("master_profile")), follow_up.field):
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
    """The interview so far, as the planner reads it.

    Confidence rides along on each recorded value. A name the extractor was only 70% sure
    of is exactly the thing worth confirming inside the next question, in passing, rather
    than in a turn of its own that asks "is this right?" about a word the user just typed.
    """
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
    resume = _as_dict(state.get("master_profile"))

    waiting = "\n".join(
        f"- {g.get('field')} (priority {g.get('kind')}, section {g.get('section')}): {g.get('reason', '')}"
        for g in queue
    )

    follow_up_rule = """
    1. Look at the MOST RECENT answer. Set `follow_up` ONLY if one of these is true:
         a. It answered part of what was asked and the rest still matters.
         b. It contradicts something recorded above — two different end dates for one job,
            a title that does not fit the dates, the same employer listed twice.
         c. Something was recorded that the extractor was unsure of, and getting it wrong
            would be embarrassing on a resume. Confirm it inside a natural question.
         d. It named something substantial — a product, a system, a team they ran — and
            said almost nothing about it. One more question about the scale, the stack,
            or what changed as a result is worth more than any question in the list below.
       An answer marked "rated thin" or "rated unusable" above is the strongest signal
       there is: the phrase after the rating says exactly what is missing, so ask about
       that and nothing else. An answer with no rating line was good enough — do not go
       back to it unless it contradicts something (b).
       Anything the waiting list below already covers is NOT a follow-up: that question is
       already scheduled, and asking it twice is how an interview turns into an
       interrogation. Match depth to substance — a thin answer about a phone number is
       just a phone number. If none of a/b/c/d applies, leave `follow_up` null; on most
       turns it is null.
    """ if may_follow_up else """
    1. Leave `follow_up` null this turn. You have already acted on every exchange above,
       so there is no new answer to judge.
    """

    prompt = f"""
    You are running a resume interview, one question at a time. Decide what to ask next.

    WHAT THE RESUME HOLDS SO FAR ({state.get("completion") or 0}% of its fields are filled):
    {json.dumps({k: v for k, v in resume.items() if v}, ensure_ascii=False)}

    THE INTERVIEW SO FAR:
    {transcript(state.get("exchanges") or [])}

    QUESTIONS WAITING TO BE ASKED — any one of these can be next:
    {waiting}

    Already given up on: {state.get("skipped") or "nothing"}

    Judge, in this order:
    {follow_up_rule}
    2. Is anything in the waiting list not worth asking any more? If what is already
       recorded tells a hiring manager who this person is and what they have done, name
       every remaining optional section in `drop_sections` and end the interview there.
       A finished resume now beats a marginally fuller one five questions later. Sections
       holding a required gap are not yours to drop; naming them does nothing.
    3. Of what is left IN THE SECTION ALREADY ON THE TABLE, which single question buys
       the most? Weigh what an answer would come back with, not how many boxes it ticks:
       "what did you build, and what changed because of it" yields the technologies, the
       scale and the outcome at once, while a profile URL yields one string. Evidence
       beats completeness. Do not name a field from another section — finish this one
       first; the waiting list is already in the order the sections should be covered.

    Rules:
    - A follow-up must name a path that appears above and real field names of that item.
      A question whose answer has nowhere to be stored is worse than no question.
    - Never re-open anything in the given-up list. Silence is the cheaper mistake: a
      question they did not need costs them more than a marginally thinner bullet gains.
    - `next_field` must be copied from the waiting list above, or left empty.
    """

    try:
        return get_openai_llm().with_structured_output(
            TurnPlan, method="function_calling"
        ).invoke(prompt)
    except Exception as e:
                                                                                     
        logger.error("Conversation planner failed, falling back to queue order: %r", e)
        return None

def conversation_planner(state: ResumeState) -> Dict[str, Any]:
    """Choose the next question. Writes `active_target`, and the queue it came from.

    active_target MUST be question_queue[0]: merge_profile and validate_entities both
    advance the queue by popping the head, so a target that isn't the head pops the
    wrong gap and silently loses a question.
    """
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

if __name__ == "__main__":
    def gap(field, kind="required", section=None, is_gate=False):
        return {"field": field, "kind": kind, "is_gate": is_gate,
                "section": section or field.partition("[")[0], "reason": ""}

    def turn(field, answer="Acme", follow_up=False, judged=True, values=None, confidence=None,
             sufficiency="sufficient", gap=""):
        return {"question": "?", "answer": answer, "field": field, "values": values or {},
                "confidence": confidence or {}, "follow_up": follow_up, "judged": judged,
                "sufficiency": sufficiency, "gap": gap}

    def probe(why="thin", field="experience[0]", fields=("highlights",), question="What changed?"):
        return FollowUp(field=field, fields=list(fields), question=question, why=why)

    GATE = gap("career_level", is_gate=True)
    JOBS = [gap("experience[0]"), gap("experience[1]"), gap("basics")]

    assert candidates([GATE, *JOBS]) == [GATE]

    jobs = [gap("experience[0]"), gap("experience[1]"), gap("basics")]
    assert [g["field"] for g in candidates(jobs)] == ["experience[0]", "experience[1]"]

    half_done = [gap("education[0]", kind="recommended"), gap("basics", kind="recommended"),
                 gap("projects[0]", kind="recommended")]
    assert [g["field"] for g in candidates(half_done)] == ["education[0]"]

    tiered = [gap("experience[0]"), gap("experience[1]", kind="recommended")]
    assert [g["field"] for g in candidates(tiered)] == ["experience[0]"]

    mixed = [gap("experience[0]"), gap("projects[0]", kind="recommended"), gap("basics")]

    queue = [gap("experience[0]"), gap("projects[0]", kind="recommended")]
    assert droppable(["projects"], queue) == {"projects"}
    assert droppable(["experience"], queue) == set(), "a required gap is not droppable"
    assert droppable(["hobbies", ""], queue) == set(), "only sections actually queued"
                                                                                
    optional = [gap("projects[0]", kind="recommended"), gap("basics", kind="recommended")]
    assert droppable(["projects", "basics"], optional) == {"projects", "basics"}

    reordered = promote(mixed, "basics")
    assert [g["field"] for g in reordered] == ["basics", "experience[0]", "projects[0]"], reordered
    assert promote(mixed, "experience[0]") == mixed, "already first is a no-op"
    assert len(reordered) == len(mixed), "reordering must not drop a gap"

    history = [
        turn("experience[0]", "Acme, 2019 to 2021", values={"company": "Acme"}),
        turn("experience[0]", "Careerboat actually", follow_up=True, judged=False,
             values={"company": "Careerboat"}, confidence={"company": 0.55}),
    ]
    text = transcript(history)
    assert "MOST RECENT, not yet acted on" in text, "the planner must know which answer is new"
    assert text.count("MOST RECENT") == 1, "only the unjudged exchange is up for judgement"
    assert "[a follow-up you asked]" in text, "so it can see how deep it has already probed"
    assert "55% sure of company" in text, text
    assert "2019 to 2021" in text, "a contradiction two turns back is only visible in history"
                                                                      
    assert "sure of" not in transcript([turn("basics", values={"phone": "1"}, confidence={"phone": 1.0})])
    assert transcript([]).startswith("Nothing yet")

    assert len(unjudged({"exchanges": history})) == 1
    assert unjudged({}) == []
    retired = mark_judged({"exchanges": history})["exchanges"]
    assert all(e["judged"] for e in retired), "judged once, then kept as context"
    assert len(retired) == 2, "acting on an exchange must not drop it from the transcript"
    assert mark_judged({"exchanges": retired}) == {}, "nothing to retire, nothing to write"

    thin = [turn("projects[0]", judged=False, sufficiency="thin", gap="named it, said nothing about it")]
    good = [turn("projects[0]", judged=False)]

    assert worth_probing(probe(), thin), "a thin answer is exactly what a follow-up is for"
    assert worth_probing(probe(), [turn("basics", judged=False, sufficiency="unusable")])
    assert not worth_probing(probe(), good), "sufficient means stop, whatever the topic"
    assert not worth_probing(probe(), []), "nothing pending, nothing to probe"
    assert not worth_probing(None, thin), "no follow-up proposed, nothing to allow"

    assert worth_probing(probe(why="contradiction"), good)
                                                                                       
    for excuse in ("thin", "incomplete", "unsure"):
        assert not worth_probing(probe(why=excuse), good), excuse

    rated = transcript(thin)
    assert "rated thin: named it, said nothing about it" in rated, rated
    assert "rated" not in transcript(good), "a good answer needs no note"

    probed = [turn("projects[0]", follow_up=True), turn("basics", follow_up=True),
              turn("projects[0]", follow_up=False)]
    assert probe_depth({"exchanges": probed}, "projects[0]") == 1, "only follow-ups count as probes"
    assert probe_depth({"exchanges": probed}, "education[0]") == 0

    PROFILE = {"experience": [{"company": "Acme", "position": "Engineer", "end_date": ""}]}
    ok = probe(why="incomplete", fields=("end_date",), question="Are you still at Acme?")

    item = usable_follow_up(ok, {"master_profile": PROFILE}, [])
    assert item["section"] == "experience" and item["missing_fields"] == ["end_date"]
    assert item["question_text"] == "Are you still at Acme?"
    assert item["is_gate"] is False, "a follow-up must not clear the queue on answer"

    from app.graphs.apply import apply_extraction
    landed = apply_extraction(PROFILE, item["field"], {f: "Present" for f in item["missing_fields"]})
    assert landed["experience"][0]["end_date"] == "Present", landed

    assert usable_follow_up(
        probe(field="experience[9]", fields=("end_date",)), {"master_profile": PROFILE}, []
    ) is None
                                                                     
    assert usable_follow_up(ok, {"master_profile": {}}, [gap("experience[0]")]) is not None

    assert usable_follow_up(probe(field="basics", fields=()), {"master_profile": PROFILE}, []) is None
    assert usable_follow_up(probe(field="basics", fields=("phone",), question="  "),
                            {"master_profile": PROFILE}, []) is None

    assert usable_follow_up(ok, {"master_profile": PROFILE, "follow_ups_asked": MAX_FOLLOW_UPS}, []) is None
    assert usable_follow_up(ok, {"master_profile": PROFILE, "follow_ups_asked": MAX_FOLLOW_UPS - 1}, []) is not None
                                                                                           
    deep = {"master_profile": PROFILE,
            "exchanges": [turn("experience[0]", follow_up=True)] * MAX_PROBE_DEPTH}
    assert usable_follow_up(ok, deep, []) is None
    shallow = {"master_profile": PROFILE, "exchanges": [turn("experience[0]", follow_up=True)]}
    assert MAX_PROBE_DEPTH < 2 or usable_follow_up(ok, shallow, []) is not None
                                                                                   
    assert usable_follow_up(probe(field="basics", fields=("phone",), question="Number?"),
                            {**deep, "master_profile": {"basics": {"name": "S"}}}, []) is not None

    assert conversation_planner({"question_queue": []}) == {"active_target": None}

    first = conversation_planner({"question_queue": [GATE, *JOBS], "master_profile": {}})
    assert first["active_target"] is GATE

    retry = conversation_planner({
        "question_queue": JOBS, "validation_errors": ["nope"], "master_profile": {},
        "exchanges": [turn("experience[0]", judged=False)],
    })
    assert retry["active_target"] is JOBS[0]
    assert all(e["judged"] for e in retry["exchanges"]), "a re-ask still retires the exchange"

    settled = conversation_planner({
        "question_queue": [GATE, *JOBS], "master_profile": {},
        "exchanges": [turn("experience[0]")],
    })
    assert settled["active_target"] is GATE, "nothing pending and one candidate: no call"

    print("conversation_planner ok")
