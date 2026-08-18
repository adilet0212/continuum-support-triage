"""
A mock LLM provider, registered through Continuum's own provider registry.

Why this layer and not a stubbed AgentRunner or BaseAgent: intercepting at the
provider means everything above it still executes for real -- ParallelAgent's
concurrency, the STRUCTURED merge, schema_prompt injection, and
coerce_and_validate. Mocking any higher would mean the code under test is not
the code that ships.

`register_provider` is a documented extension point (see the module docstring of
continuum/llm/providers/__init__.py), so this is framework-native, not a
workaround.

Usage:
    from src.mock_provider import register_mock_provider
    register_mock_provider()          # call once, before building agents
    # then give agents model="mock/gpt-4o-mini"

Caveat: if SMART_GATEWAY_URL is set in the environment, Continuum routes every
model through the gateway and this registration is silently bypassed (it logs a
warning once). Keep that variable unset.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

from continuum.llm.config import LLMConfig
from continuum.llm.providers import BaseProvider, register_provider
from continuum.llm.types import LLMResponse, StreamChunk

from src.fixtures import RESPONSES, TICKET_MARKERS

MOCK_PREFIX = "mock/"


class MockResponseNotFound(RuntimeError):
    """No fixture matched the prompt -- a missing fixture, not an LLM failure."""


def _detect_ticket_id(prompt: str) -> int | None:
    """Work out which ticket a prompt is about by looking for its marker text."""
    lowered = prompt.lower()
    for ticket_id, marker in TICKET_MARKERS.items():
        if marker.lower() in lowered:
            return ticket_id
    return None


def _detect_agent_kind(prompt: str) -> str | None:
    """Work out which agent is calling from the field names in the schema prompt.

    Continuum injects schema_prompt(output_schema) as a system message, which
    lists the field names of the expected model. Those field sets are distinct
    per agent, so they identify the caller without the mock needing to know
    anything about agent names.
    """
    lowered = prompt.lower()
    if '"response_message"' in lowered or "response_message" in lowered:
        return "resolution"
    if '"category"' in lowered or "category" in lowered:
        return "classification"
    if '"priority"' in lowered or "priority" in lowered:
        return "priority"
    return None


def _flatten(messages: list[dict[str, Any]]) -> str:
    """Join every message's text content into one searchable string."""
    parts: list[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            # Some providers use content blocks; take any text we find.
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
    return "\n".join(parts)


def lookup_response(messages: list[dict[str, Any]]) -> str:
    """Return the canned JSON string for this prompt, or raise if none matches."""
    prompt = _flatten(messages)
    ticket_id = _detect_ticket_id(prompt)
    agent_kind = _detect_agent_kind(prompt)

    if ticket_id is None or agent_kind is None:
        raise MockResponseNotFound(
            f"could not identify prompt (ticket_id={ticket_id}, "
            f"agent_kind={agent_kind})"
        )

    try:
        return RESPONSES[(ticket_id, agent_kind)]
    except KeyError:
        raise MockResponseNotFound(
            f"no fixture for ticket {ticket_id}, agent {agent_kind}"
        ) from None


class MockProvider(BaseProvider):
    """Returns canned responses. Never touches the network."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    def _respond(self, messages: list[dict[str, Any]]) -> LLMResponse:
        return LLMResponse(
            model=self._config.model,
            content=lookup_response(messages),
            role="assistant",
            finish_reason="stop",
        )

    def complete(
        self,
        messages: list[dict[str, Any]],
        config: LLMConfig,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        return self._respond(messages)

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        config: LLMConfig,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        return self._respond(messages)

    def stream(
        self,
        messages: list[dict[str, Any]],
        config: LLMConfig,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> Iterator[StreamChunk]:
        raise NotImplementedError("MockProvider does not support streaming.")

    async def astream(
        self,
        messages: list[dict[str, Any]],
        config: LLMConfig,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        raise NotImplementedError("MockProvider does not support streaming.")


def register_mock_provider() -> None:
    """Route every model named 'mock/...' to MockProvider. Safe to call twice."""
    register_provider(MOCK_PREFIX, lambda config, settings: MockProvider(config))