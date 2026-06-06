"""Minimal agent worker process for local development.

Task 1 wires process topology before command consumption exists. Keeping this
process alive prevents `dev-start.sh` from advertising a missing module.
"""

from __future__ import annotations

import signal
import time


def startup_message(label: str) -> str:
    return f"{label} started; command handling will be implemented in a later task."


def run_forever(label: str) -> None:
    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(startup_message(label), flush=True)
    while running:
        time.sleep(1)


def main() -> None:
    run_forever("agent worker")


if __name__ == "__main__":
    main()
