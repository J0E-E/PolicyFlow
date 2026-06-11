"""Seed placeholder for the core service.

This is the importable, testable seam that P1.8 fills with real seed data. For
now it only logs that there is nothing to seed yet. The entrypoint runs it via
``python -m app.seed`` after migrations and before the app serves traffic.
"""

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run() -> None:
    """Run the seed step. Placeholder — no seed data exists yet (P1.8)."""
    logger.info("no seed data yet (placeholder for P1.8)")


if __name__ == "__main__":
    run()
