from src.state import TicketState, TicketStatus
from src.schemas import TicketCategory, TicketPriority

CONFIDENCE_THRESHOLD = 0.7

def decide(state: TicketState) -> tuple[TicketStatus, str]:

    # Guard order matters. A None slot means schema validation failed upstream
    # (output_schema_strict is False, so that fails quietly) and must be caught
    # before anything reads .category or .confidence off it.
    if state.classification is None or state.prioritization is None:
        return TicketStatus.escalated, "classification or priority failed schema validation"
    if state.classification.confidence < CONFIDENCE_THRESHOLD:
        return TicketStatus.escalated, f"confidence {state.classification.confidence} below threshold {CONFIDENCE_THRESHOLD}"

    category = state.classification.category
    priority = state.prioritization.priority
    is_auto_resolvable = (
        category == TicketCategory.feedback or
        (category == TicketCategory.general and priority == TicketPriority.low)
    )

    if is_auto_resolvable:
        return TicketStatus.resolved, "category and priority are auto-resolvable"
    
    return TicketStatus.escalated, "not in the auto-resolvable set"