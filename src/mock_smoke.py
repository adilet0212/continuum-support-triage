import asyncio
from continuum.agent import BaseAgent, AgentRunner
from src.schemas import ClassificationOutput
from src.mock_provider import register_mock_provider

async def main():
    register_mock_provider()
    agent = BaseAgent(
        name="ticket_agent",
        instructions="You are a ticketing agent that correctly classifies, prioritizes"
        " and resolves or escalates client tickets based on their types and content",
        model="mock/gpt-4o-mini",
        output_schema=ClassificationOutput
    )
    runner = AgentRunner()
    response = await runner.run(agent, "Cannot access my account. I've been trying to log in for the past hour but keep getting 'invalid password' even though I'm sure it's correct.")
    print(response.content)
    print(response.structured_output)

    response2 = await runner.run(agent, "zzz malformed ticket zzz")
    print(response2.structured_output)

if __name__ == "__main__":
    asyncio.run(main())