"""
logger.py — Logging setup for the package.

Two outputs:
  1. Console: human-readable timestamped lines (DEBUG-or-higher).
  2. logs/run_log.jsonl: append-only JSONL, one line per filing processed.

The JSONL log is structured for downstream querying — see README.md for
the schema. It's only written via `log_run()`, not by the standard
logging machinery.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_LOG_FORMAT = "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s"


def setup_logging(level: int = logging.INFO, log_dir: Path | None = None) -> None:
    """
    Configure root logging. Console only — the structured run log uses
    a separate `log_run()` call.
    """
    logging.basicConfig(
        level=level,
        format=_DEFAULT_LOG_FORMAT,
        handlers=[logging.StreamHandler()],
        force=True,  # override any prior basicConfig
    )


def log_run(
    log_dir: Path,
    source_file: str,
    status: str,
    elapsed: float,
    facts_total: int = 0,
    output_file: str | None = None,
    error: str | None = None,
) -> None:
    """
    Append one record to logs/run_log.jsonl.

    Status is one of: "success", "parse_error", "io_error".
    The file is created on first call; never rewritten.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "run_log.jsonl"

    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_file": source_file,
        "status": status,
        "elapsed_seconds": round(elapsed, 3),
        "facts_total": facts_total,
        "output_file": output_file,
        "error": error,
    }

    with open(path, "a") as fh:
        fh.write(json.dumps(record) + "\n")
