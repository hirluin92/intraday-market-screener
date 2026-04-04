"""
MVP logging: ensure application loggers emit INFO to stdout (visible in ``docker logs``).

Uvicorn configures its own loggers; we align root + ``app.*`` + ``apscheduler`` to INFO
and attach a stdout handler to the root logger when none exists (typical in containers).
"""

from __future__ import annotations

import logging
import sys


def configure_application_logging() -> None:
    """Idempotent: safe to call from lifespan on every startup."""
    log_format = "%(levelname)s [%(name)s] %(message)s"
    formatter = logging.Formatter(log_format)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    else:
        for h in root.handlers:
            if h.level > logging.INFO:
                h.setLevel(logging.INFO)

    # Application code and in-process scheduler
    logging.getLogger("app").setLevel(logging.INFO)
    logging.getLogger("apscheduler").setLevel(logging.INFO)
    logging.getLogger("apscheduler.scheduler").setLevel(logging.INFO)

    # Keep uvicorn access/error visible at INFO alongside app logs
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
