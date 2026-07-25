import logging
from typing import Any, Dict
from app.graphs.state import ResumeState

logger = logging.getLogger(__name__)

def prioritize_queue(state: ResumeState) -> Dict[str, Any]:
    """
    Pure Python deterministic orchestration.
    Peeks at the top of question_queue and stores it in state.active_target.
    Does NOT pop the item, to ensure it is re-asked if validation fails.
    """
    queue = state.get("question_queue", [])
    if not queue:
        return {"active_target": None}

    target_gap = queue[0]

    logger.info(f"Prioritized target gap: {target_gap.get('field')}")
    return {"active_target": target_gap}
