"""Minimal outbox publisher process for local development."""

from __future__ import annotations

from worker.main import run_forever


def main() -> None:
    run_forever("outbox publisher")


if __name__ == "__main__":
    main()
