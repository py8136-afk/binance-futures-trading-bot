"""
Logging configuration.

Two sinks, on purpose:
  - logs/bot.log  -> DEBUG, full request/response JSON, rotated. This is the
                     forensic record the task asks us to submit.
  - console       -> INFO, clean one-liners for the human running the CLI.

A RedactionFilter scrubs API keys and signatures from *every* record before it
is written, so the log file is safe to commit/share.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "bot.log"

# Patterns that should never appear in clear text in a log line.
_SIG_RE = re.compile(r"(signature=)[0-9a-fA-F]+")
_KEY_HEADER_RE = re.compile(r"(X-MBX-APIKEY['\"]?\s*[:=]\s*['\"]?)([A-Za-z0-9]+)")


class RedactionFilter(logging.Filter):
    """Strip signatures and API keys out of formatted log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        msg = _SIG_RE.sub(r"\1<redacted>", msg)
        msg = _KEY_HEADER_RE.sub(r"\1<redacted>", msg)
        record.msg = msg
        record.args = ()
        return True


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("bot")
    logger.setLevel(logging.DEBUG)

    # Avoid stacking duplicate handlers if setup is called more than once.
    if logger.handlers:
        return logger

    redaction = RedactionFilter()

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    )
    file_handler.addFilter(redaction)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter("%(levelname)-7s | %(message)s"))
    console_handler.addFilter(redaction)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger
