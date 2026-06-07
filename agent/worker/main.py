from __future__ import annotations

import asyncio

from worker.command_consumer import run_consumer

def startup_message(label: str) -> str:
    return f"{label} started; consuming command queues."


async def run_worker(label: str = "agent worker") -> None:
    print(startup_message(label), flush=True)
    await run_consumer()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
