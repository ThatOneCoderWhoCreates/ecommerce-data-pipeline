"""Logging setup: writes to the console and to a timestamped file in the log folder."""

import logging
from datetime import datetime
from pathlib import Path

LOGGER_NAME = "pipeline"


def setup_logging(log_dir, level="INFO"):
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"pipeline_{datetime.now():%Y%m%d_%H%M%S}.log"

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(module)-9s | %(message)s", "%Y-%m-%d %H:%M:%S")
    for handler in (logging.StreamHandler(), logging.FileHandler(log_file, encoding="utf-8")):
        handler.setFormatter(fmt)
        logger.addHandler(handler)

    logger.info("Logging to %s", log_file)
    return logger, log_file


def get_logger():
    return logging.getLogger(LOGGER_NAME)
