"""
Centralized logging configuration with structured JSON output for production.
"""

import logging
import sys
from app.config import settings


def setup_logging() -> None:
    """Configure application-wide logging.

    - Development: human-readable format with timestamps.
    - Production: structured format suitable for log aggregators.
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    if settings.environment == "development":
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    else:
        # Structured key=value format, easy to parse by log aggregators
        fmt = (
            "time=%(asctime)s level=%(levelname)s logger=%(name)s "
            "message=%(message)s"
        )

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )

    # Silence noisy third-party loggers
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
