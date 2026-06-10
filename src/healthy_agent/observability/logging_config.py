"""Structured logging configuration.

Provides JSON-structured logging for production and
human-readable colored output for development.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any


class StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter for production."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["error"] = str(record.exc_info[1])
            log_entry["error_type"] = type(record.exc_info[1]).__name__
        if hasattr(record, "extra_data"):
            log_entry.update(record.extra_data)
        return json.dumps(log_entry, ensure_ascii=False)


class DevFormatter(logging.Formatter):
    """Colored human-readable formatter for development."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        ts = time.strftime("%H:%M:%S", time.localtime(record.created))
        name = record.name.replace("healthy_agent.", "")
        return f"{color}{ts} [{record.levelname[0]}] {name}: {record.getMessage()}{self.RESET}"


def setup_logging(
    *,
    level: str = "INFO",
    structured: bool = False,
    log_file: str | None = None,
) -> None:
    """Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        structured: If True, use JSON output (for production).
        log_file: Optional file path to write logs to.
    """
    root = logging.getLogger("healthy_agent")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    formatter = StructuredFormatter() if structured else DevFormatter()

    # Console handler
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    root.addHandler(console)

    # File handler (always structured)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(StructuredFormatter())
        root.addHandler(file_handler)

    root.propagate = False

    # Unify uvicorn loggers to use our formatter
    for uvicorn_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(uvicorn_logger_name)
        uv_logger.handlers.clear()
        uv_logger.addHandler(console)
        uv_logger.propagate = False
