"""Tests for the resolve/escalate gate.

The gate is a pure function over already-validated fields, so every branch can
be asserted directly with no API key and no model involved. That testability is
the main reason it is a code branch and not a RouterAgent (decision 3).
"""

import pytest

from src.gate import decide, CONFIDENCE_THRESHOLD
from src.schemas import (
    ClassificationOutput,
    PriorityOutput,
    TicketCategory,
    TicketPriority,
)
from src.state import TicketState, TicketStatus


def build_state(
    category: TicketCategory | None = TicketCategory.general,
    priority: TicketPriority | None = TicketPriority.low,
    confidence: float = 0.95,
) -> TicketState:
    """A ticket that has already been through the parallel stage.

    Passing None for category or priority leaves that slot empty, which is what
    the pipeline does when an agent's output fails schema validation.
    """
    state = TicketState(
        ticket_id=1,
        title="test ticket",
        description="test description",
        customer_email="test@example.invalid",
    )
    if category is not None:
        state.classification = ClassificationOutput(
            category=category, confidence=confidence, reason="test"
        )
    if priority is not None:
        state.prioritization = PriorityOutput(priority=priority, reason="test")
    return state


# --- guard 1: a slot never filled because validation failed -----------------

def test_missing_classification_escalates():
    decision, reason = decide(build_state(category=None))
    assert decision == TicketStatus.escalated
    assert "schema validation" in reason


def test_missing_priority_escalates():
    decision, reason = decide(build_state(priority=None))
    assert decision == TicketStatus.escalated
    assert "schema validation" in reason


def test_both_missing_escalates():
    decision, _ = decide(build_state(category=None, priority=None))
    assert decision == TicketStatus.escalated


# --- guard 2: low confidence ------------------------------------------------

def test_low_confidence_escalates():
    # feedback would otherwise resolve, so this proves the guard is what stops it
    state = build_state(category=TicketCategory.feedback, confidence=0.5)
    decision, reason = decide(state)
    assert decision == TicketStatus.escalated
    assert "confidence" in reason


def test_confidence_exactly_at_threshold_passes():
    # the comparison is <, not <=, so 0.7 is not low enough to escalate on its own
    state = build_state(category=TicketCategory.feedback, confidence=CONFIDENCE_THRESHOLD)
    decision, reason = decide(state)
    assert decision == TicketStatus.resolved
    assert "confidence" not in reason


# --- the auto-resolvable set ------------------------------------------------

@pytest.mark.parametrize(
    "priority",
    [
        TicketPriority.low,
        TicketPriority.medium,
        TicketPriority.high,
        TicketPriority.critical,
    ],
)
def test_feedback_resolves_at_any_priority(priority):
    # feedback asks for nothing, so urgency does not change the outcome
    decision, _ = decide(build_state(category=TicketCategory.feedback, priority=priority))
    assert decision == TicketStatus.resolved


def test_general_low_resolves():
    decision, _ = decide(
        build_state(category=TicketCategory.general, priority=TicketPriority.low)
    )
    assert decision == TicketStatus.resolved


@pytest.mark.parametrize(
    "priority",
    [TicketPriority.medium, TicketPriority.high, TicketPriority.critical],
)
def test_general_above_low_escalates(priority):
    # a general question that is not routine is a human's call
    decision, _ = decide(build_state(category=TicketCategory.general, priority=priority))
    assert decision == TicketStatus.escalated


@pytest.mark.parametrize(
    "category",
    [TicketCategory.billing, TicketCategory.technical, TicketCategory.account],
)
def test_other_categories_escalate(category):
    decision, reason = decide(build_state(category=category, priority=TicketPriority.low))
    assert decision == TicketStatus.escalated
    assert "auto-resolvable" in reason


# --- the gate does not mutate state ----------------------------------------

def test_decide_does_not_transition():
    """decide() returns a decision; only the pipeline records it.

    history has one entry from __post_init__ ('received') and the gate must not
    add another - transitions are recorded by the caller, not the gate.
    """
    state = build_state()
    before = len(state.history)
    decide(state)
    assert len(state.history) == before
    assert state.status == TicketStatus.received