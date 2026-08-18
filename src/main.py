import asyncio, logging, argparse
from continuum.agent import AgentRunner
from src.mock_provider import register_mock_provider
from src.state import TicketState
from src.pipeline import process_ticket

TEST_TICKETS = [
    {
        "id": 1,
        "title": "Cannot access my account",
        "description": "I've been trying to log in for the past hour but keep getting 'invalid password' even though I'm sure it's correct.",
        "customer_email": "john@example.com"
    },
    {
        "id": 2,
        "title": "Charged twice this month",
        "description": "My credit card shows two charges of $99.99 for this month. I should only be charged once. Please refund immediately.",
        "customer_email": "sarah@example.com"
    },
    {
        "id": 3,
        "title": "API returning 500 errors",
        "description": "Our production system is down. The /api/v2/users endpoint is returning 500 errors for the past 20 minutes. URGENT.",
        "customer_email": "devteam@enterprise.com"
    },
    {
        "id": 4,
        "title": "How do I export my data?",
        "description": "I need to download all my data for my records. Where can I find the export feature?",
        "customer_email": "mary@example.com"
    },
    {
        "id": 5,
        "title": "Love your product!",
        "description": "Just wanted to say the new dashboard update is amazing. Great work team!",
        "customer_email": "happy@customer.com"
    }
]

# Synthetic ticket used to force a schema-validation failure. Its mocked
# classifier response returns a category outside TicketCategory, so Pydantic
# rejects it, the classification slot stays None and the gate escalates.
FAULT_TICKETS = [
    {
        "id": 99,
        "title": "Synthetic fault-injection ticket",
        "description": "zzz malformed ticket zzz",
        "customer_email": "test@example.invalid"
    }
]

async def main(tickets: list[dict]) -> None:
    logging.basicConfig(level=logging.INFO)
    register_mock_provider()
    runner = AgentRunner()
    for ticket in tickets:
        state = TicketState(
            ticket_id=ticket["id"],
            title=ticket["title"],
            description=ticket["description"],
            customer_email=ticket["customer_email"],
        )
        await process_ticket(state, runner)
        print(f"\n--- ticket {state.ticket_id}: {state.status.value} ---")
        for status, _timestamp, reason in state.history:
            print(f"  {status.value:12} {reason}")

        if state.classification and state.prioritization:
            print(f"  -> {state.classification.category.value} / "
                  f"{state.prioritization.priority.value} "
                  f"(confidence {state.classification.confidence})")
            
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the support ticket triage pipeline.")
    parser.add_argument(
        "--fault",
        action="store_true",
        help="Run the synthetic fault-injection ticket instead of the sample tickets.",
    )
    args = parser.parse_args()
    asyncio.run(main(FAULT_TICKETS if args.fault else TEST_TICKETS))