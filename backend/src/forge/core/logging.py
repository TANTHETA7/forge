"""Logging setup.

Purpose:       Configure a single, consistent logging format for the whole process.
Responsibility: stdlib `logging` configuration only — no business logic.
Why it exists: Every layer logs; without one setup call each module would configure
                its own handlers, producing duplicated or inconsistent output.
Depends on:    stdlib `logging` only.
Depended on by: core/app_factory.py (called once at startup).
"""

import logging
import sys

from forge.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure the root logger's format and level for the current environment.

    Args:
        settings: Application settings; ``environment`` controls verbosity
            (DEBUG in development, INFO otherwise).
    """
    level = logging.DEBUG if settings.environment == "development" else logging.INFO
    logging.basicConfig(
        level=level,
        stream=sys.stdout,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        force=True,
    )
