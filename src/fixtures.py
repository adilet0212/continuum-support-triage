"""
Canned LLM responses used during development so the pipeline can be exercised
end to end without spending real API calls.

Each entry maps (ticket_id, agent_kind) -> the raw JSON *string* a real provider
would put in `LLMResponse.content`. Returning a string, not a Pydantic object,
is deliberate: it keeps Continuum's own parse-and-validate path
(`coerce_and_validate` in continuum/llm/structured_output.py) in the loop, so
what runs against mocks is the same code that runs against OpenAI.

Ticket 99 is a synthetic ticket whose classifier response is intentionally
invalid (category is not a member of TicketCategory). It exists to force the
schema-validation failure path.
"""

# Substrings used to work out which ticket a prompt is about. The provider only
# sees chat messages, never a ticket id, so we match on distinctive text.
TICKET_MARKERS: dict[int, str] = {
    1: "invalid password",
    2: "two charges",
    3: "/api/v2/users",
    4: "export feature",
    5: "dashboard update is amazing",
    99: "zzz malformed ticket zzz",
}

RESPONSES: dict[tuple[int, str], str] = {
    # --- ticket 1: login failure -------------------------------------------
    (1, "classification"): (
        '{"category": "account", "confidence": 0.93, '
        '"reason": "Customer cannot log in despite a correct password, so the '
        'problem is account access."}'
    ),
    (1, "priority"): (
        '{"priority": "medium", "reason": "A single user is blocked but no '
        'system is down and there is no financial impact."}'
    ),
    (1, "resolution"): (
        '{"resolved": true, "response_message": "Please reset your password '
        'using the Forgot Password link on the sign-in page. If the reset '
        'email does not arrive within ten minutes, check your spam folder."}'
    ),

    # --- ticket 2: duplicate charge ----------------------------------------
    (2, "classification"): (
        '{"category": "billing", "confidence": 0.97, '
        '"reason": "Two charges of the same amount in one month is a payment '
        'and refund issue."}'
    ),
    (2, "priority"): (
        '{"priority": "high", "reason": "The customer has been charged twice '
        'and is out of pocket, but no system is broken."}'
    ),

    # --- ticket 3: production outage ---------------------------------------
    (3, "classification"): (
        '{"category": "technical", "confidence": 0.98, '
        '"reason": "A production API endpoint is returning 500 errors."}'
    ),
    (3, "priority"): (
        '{"priority": "critical", "reason": "Production is down for an '
        'enterprise customer and has been for twenty minutes."}'
    ),

    # --- ticket 4: how-to question -----------------------------------------
    (4, "classification"): (
        '{"category": "general", "confidence": 0.95, '
        '"reason": "The customer is asking where to find an existing feature, '
        'not reporting a problem."}'
    ),
    (4, "priority"): (
        '{"priority": "low", "reason": "A routine informational question with '
        'no time pressure."}'
    ),
    (4, "resolution"): (
        '{"resolved": true, "response_message": "You can export your data from '
        'Settings > Account > Export Data. The export is emailed to you as a '
        'ZIP archive, usually within a few minutes."}'
    ),

    # --- ticket 5: praise, no request --------------------------------------
    (5, "classification"): (
        '{"category": "feedback", "confidence": 0.96, '
        '"reason": "The customer is praising the product and asking for '
        'nothing."}'
    ),
    (5, "priority"): (
        '{"priority": "low", "reason": "No action is required and nothing is '
        'time sensitive."}'
    ),
    (5, "resolution"): (
        '{"resolved": true, "response_message": "Thank you for the kind words '
        'about the new dashboard. We have passed your note along to the team."}'
    ),

    # --- ticket 99: forced schema-validation failure ------------------------
    # "urgent_thing" is not a member of TicketCategory, so Pydantic rejects it.
    # Continuum logs a warning and returns structured_output=None rather than
    # raising, because BaseAgent.output_schema_strict defaults to False.
    (99, "classification"): (
        '{"category": "urgent_thing", "confidence": 0.4, '
        '"reason": "Deliberately invalid category used to exercise the '
        'validation-failure path."}'
    ),
    (99, "priority"): (
        '{"priority": "medium", "reason": "Placeholder."}'
    ),
}