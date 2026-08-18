"""CLI entry point. Runs the five sample tickets through the triage pipeline.

Equivalent to 'python -m src.main'. The fault-injection demo lives there too:
'python -m src.main --fault'.
"""

import asyncio

from src.main import main, TEST_TICKETS

if __name__ == "__main__":
    asyncio.run(main(TEST_TICKETS))