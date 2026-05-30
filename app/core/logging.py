"""Structured logging via structlog. Console-friendly in dev, JSON-ready for prod.

Usage:
    from app.core.logging import get_logger, configure_logging
    configure_logging()                 # call once at app/script entry
    log = get_logger(__name__)
    log.info("event_name", key=value)   # structured key-value style
"""
import contextlib
import logging
import sys

import structlog

from app.core.config import settings


def configure_logging() -> None:
    # Force UTF-8 on the console streams. On Windows they default to cp1252,
    # which raises UnicodeEncodeError the moment any log line contains a
    # non-latin1 char (e.g. box-drawing chars from a litellm Rich error
    # panel, or emoji in agent output). A logging call that *raises* is
    # catastrophic — it can escape an error handler before the failure is
    # persisted, leaving rows wedged in 'running'. `errors="replace"` means
    # logging degrades to '?' instead of ever throwing.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            # Stream may be detached/replaced (e.g. pytest capture) — ignore.
            with contextlib.suppress(ValueError, OSError):
                reconfigure(encoding="utf-8", errors="replace")

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
