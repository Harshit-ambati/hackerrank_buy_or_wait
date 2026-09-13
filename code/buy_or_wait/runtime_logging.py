"""Concise application logging configuration."""

from __future__ import annotations

import logging


def configure_logging() -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return logging.getLogger("buy_or_wait")
