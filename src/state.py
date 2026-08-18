from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from src.schemas import ClassificationOutput, PriorityOutput, ResolutionOutput

class TicketStatus(str, Enum):
    received = "received"
    classified = "classified"
    prioritized = "prioritized"
    resolved = "resolved"
    escalated = "escalated"

@dataclass
class TicketState:
    ticket_id: int
    title: str
    description: str
    customer_email: str
    status: TicketStatus = TicketStatus.received
    history: list[tuple[TicketStatus, str, str]] = field(default_factory=list)
    classification: ClassificationOutput | None = None
    prioritization: PriorityOutput | None = None
    resolution: ResolutionOutput | None = None

    def __post_init__(self) -> None:
        """Record arrival so history covers received -> ... -> resolved/escalated."""
        self.history.append(
            (self.status, datetime.now(timezone.utc).isoformat(), "ticket received")
    )

    def transition(self, new_status: TicketStatus, reason: str = "") -> None:
        """Move to a new status and record when it happened."""
        self.status = new_status
        self.history.append((new_status, datetime.now(timezone.utc).isoformat(), reason))