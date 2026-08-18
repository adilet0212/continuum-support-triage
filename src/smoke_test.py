import asyncio
from continuum.agent import BaseAgent, AgentRunner

async def main():
    agent = BaseAgent(
        name="hello-agent",
        instructions="You are a friendly assistant.",
        model="gpt-4o-mini",
    )
    runner = AgentRunner()
    response = await runner.run(agent, "Hi!")
    print(response.content)

if __name__ == "__main__":
    asyncio.run(main())