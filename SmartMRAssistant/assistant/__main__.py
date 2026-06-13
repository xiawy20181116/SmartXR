from __future__ import annotations

import argparse
import asyncio
import json

from .session import SimulatedVoiceSession


async def _run(text: str) -> None:
    session = SimulatedVoiceSession()
    responses = await session.run_text_turn(text)
    print(json.dumps({"tool_responses": responses}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SmartMRAssistant S1 simulated voice turn.")
    parser.add_argument("--text", default="hello from SmartMRAssistant")
    args = parser.parse_args()
    asyncio.run(_run(args.text))


if __name__ == "__main__":
    main()
