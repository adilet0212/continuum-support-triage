from continuum.agent import BaseAgent, AgentRunner, create_parallel_agent, MergeStrategy
from src.state import TicketState, TicketStatus
from src.schemas import ClassificationOutput, PriorityOutput, ResolutionOutput
from src.gate import decide
import json, os, logging
from continuum.llm.structured_output import coerce_and_validate

CLASSIFIER_NAME = "classifier"
PRIORITY_NAME = "priority"
LLM_MODEL = os.getenv("DEFAULT_LLM_MODEL", "mock/gpt-4o-mini")
logger = logging.getLogger(__name__)

classifier_agent = BaseAgent(
    name=CLASSIFIER_NAME,
    instructions=(
        "You triage inbound customer support tickets for a SaaS product. "
        "Given a ticket title and description, assign exactly one category and a "
        "confidence score.\n\n"
        "Classify on what the customer is asking you to do, not on which system or "
        "feature they happen to mention. A ticket can name an API, a dashboard, or a "
        "credit card without that being the subject of the request.\n\n"
        "When two categories are genuinely defensible, choose the one matching the "
        "customer's goal and lower your confidence to reflect the ambiguity. "
        "Confidence is a real signal, not a formality: tickets below 0.7 are routed to "
        "a human rather than answered automatically. Reserve values above 0.9 for "
        "tickets that fit one category unambiguously, and use 0.5-0.7 when the ticket "
        "is vague, empty, or could reasonably be read two ways."
    ),
    model=LLM_MODEL,
    output_schema=ClassificationOutput,
    temperature=0,
)

priority_agent = BaseAgent(
    name=PRIORITY_NAME,
    instructions=(
        "You assign urgency to inbound customer support tickets for a SaaS product. "
        "Given a ticket title and description, assign exactly one priority level.\n\n"
        "Judge urgency by business impact and time sensitivity: what is broken, how "
        "many people it blocks, and whether money or data is at risk right now.\n\n"
        "Tone is not evidence. Words like URGENT, ASAP, or immediately raise priority "
        "only when the ticket also describes something that is actually broken or "
        "time-critical. A calm report of a production outage outranks an emphatic "
        "request for a routine answer. Equally, do not discount a serious problem "
        "because the customer is polite about it.\n\n"
        "If the ticket describes no problem and asks for nothing, it is not urgent."
    ),
    model=LLM_MODEL,
    output_schema=PriorityOutput,
    temperature=0,
)

resolution_agent = BaseAgent(
    name="resolution",
    instructions=(
        "You are the automated first-line responder for customer support tickets. "
        "You receive a ticket along with its assigned category and priority, and you "
        "decide whether it can be closed with a reply or must go to a human.\n\n"
        "Set resolved to true only when you can fully answer from general product "
        "knowledge alone — how a feature works, where to find a setting, what a policy "
        "says, or acknowledging feedback that needs no action.\n\n"
        "Set resolved to false whenever answering would require something you do not "
        "have: access to this customer's account or billing records, authority to issue "
        "a refund or credit, the ability to change system state, or an engineering fix. "
        "Also set it to false if the ticket is too vague to answer without guessing. "
        "In that case, state briefly what is missing and why a human is needed. Do not "
        "invent account details, transaction records, or specific settings you cannot "
        "verify.\n\n"
        "Write replies directly to the customer: plain, specific, and free of "
        "placeholder text."
    ),
    model=LLM_MODEL,
    output_schema=ResolutionOutput,
    temperature=0,
)

# create_parallel_agent, not ParallelAgent(...): the class is a dataclass with
# no merge_strategy field, so passing it to the constructor raises TypeError
# despite what the docstring shows. See decision-log.md #11.3.
triage_agent = create_parallel_agent(
    name="triage",
    agents=[classifier_agent, priority_agent],
    merge_strategy=MergeStrategy.STRUCTURED,
)

async def process_ticket(state: TicketState, runner: AgentRunner) -> TicketState:
    ticket_text = f"{state.title}\n\n{state.description}"
    response = await runner.run(triage_agent, ticket_text)

    # If every parallel branch fails, the merge is a plain-text notice rather than
    # JSON. Both slots stay None and the gate's first guard escalates so this
    # falls through to decide() instead of raising or returning early.
    try:
        merged = json.loads(response.content)
    except json.JSONDecodeError:
        logger.warning(
            "merged parallel output was not JSON for ticket %s: %r",
            state.ticket_id, response.content,
        )
        merged = {}

    raw_classification = merged.get(CLASSIFIER_NAME)

    if raw_classification is not None:
        classification, error = coerce_and_validate(raw_classification, ClassificationOutput)
        if classification is None:
            logger.warning(
                "classification validation failed for ticket %s: %s", state.ticket_id, error
            )
        else:
            state.classification = classification
            state.transition(TicketStatus.classified, "classifier output validated")

    raw_prioritization = merged.get(PRIORITY_NAME)

    if raw_prioritization is not None:
        prioritization, error = coerce_and_validate(raw_prioritization, PriorityOutput)
        if prioritization is None:
            logger.warning(
                "prioritization validation failed for ticket %s: %s", state.ticket_id, error
            )
        else:
            state.prioritization = prioritization
            state.transition(TicketStatus.prioritized, "priority output validated")

    # Routing is a pure function over validated enums, not a RouterAgent: the
    # fields are already closed types by this point, and the gate also decides
    # whether to call any agent at all. See decision-log.md #3.
    decision, reason = decide(state)

    if decision == TicketStatus.escalated:
        state.transition(TicketStatus.escalated, reason)
        return state

    resolution_prompt = (
        f"{ticket_text}\n\n"
        f"Category: {state.classification.category.value}\n"
        f"Priority: {state.prioritization.priority.value}"
    )
    resolution_response = await runner.run(resolution_agent, resolution_prompt)

    # Single-agent runs expose structured_output directly; the parallel branches
    # above had to parse it out of merged content because ParallelAgent discards
    # it. Same validation, two paths, forced by the framework. See #10.
    result = resolution_response.structured_output

    if result is None:
        logger.warning("resolution validation failed for ticket %s", state.ticket_id)
        state.transition(TicketStatus.escalated, "resolution agent returned no valid output")
        return state

    state.resolution = result
    if result.resolved:
        state.transition(TicketStatus.resolved, "resolution agent resolved the ticket")
    else:
        state.transition(TicketStatus.escalated, "resolution agent declined to resolve")

    return state