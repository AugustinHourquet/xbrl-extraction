"""
cli.py — Command-line interface.

Two modes:

  Single file:
      python -m xbrl_extraction data/input/some_filing.zip
      python -m xbrl_extraction data/input/some_filing.zip -o data/output

  Batch (every *.zip in a directory):
      python -m xbrl_extraction data/input/
      python -m xbrl_extraction data/input/ -o data/output

Output filenames are derived from the input zip basename:
  rawdata_us_1860_..._XBRL_2025-09-27.zip
  → rawdata_us_1860_..._XBRL_2025-09-27.facts.json

Idempotency: by default, a zip is skipped when its output JSON already
exists. Pass --force to re-extract everything (e.g. after an extractor
bug fix). Skipped files do NOT produce a run_log.jsonl record.

Each run appends one record per file processed (success or failure) to
logs/run_log.jsonl.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from xbrl_extraction.extractor import extract
from xbrl_extraction.logger import log_run, setup_logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

# Project root is detected by walking up from this file. The package
# lives at <root>/src/xbrl_extraction/cli.py, so root = parents[3].
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]

_DEFAULT_OUTPUT_DIR = _PACKAGE_ROOT / "data" / "output"
_DEFAULT_LOG_DIR = _PACKAGE_ROOT / "logs"


def _output_path_for(zip_path: Path, output_dir: Path) -> Path:
    """data/input/foo.zip → data/output/foo.facts.json"""
    return output_dir / f"{zip_path.stem}.facts.json"


# ---------------------------------------------------------------------------
# Single-file processing
# ---------------------------------------------------------------------------


def _process_one(
    zip_path: Path,
    output_dir: Path,
    log_dir: Path,
    force: bool = False,
) -> bool:
    """
    Extract one zip and write the JSON. Returns True on success OR skip.

    If `force` is False (default) and the output file already exists,
    the zip is skipped without invoking the extractor. The run log is
    not touched on skip — only actual extractions are logged.

    All exceptions are caught and turned into a run-log record; the
    caller decides whether to keep going with the next file.
    """
    output_path = _output_path_for(zip_path, output_dir)

    if output_path.exists() and not force:
        logger.info(
            "⊘ %s → already extracted (use --force to re-run)",
            zip_path.name,
        )
        return True

    started = time.monotonic()

    try:
        doc = extract(zip_path)
    except FileNotFoundError as exc:
        elapsed = time.monotonic() - started
        logger.error("Not found: %s", zip_path)
        log_run(log_dir, zip_path.name, status="io_error", elapsed=elapsed, error=str(exc))
        return False
    except Exception as exc:
        elapsed = time.monotonic() - started
        logger.exception("Extraction failed for %s", zip_path.name)
        log_run(
            log_dir,
            zip_path.name,
            status="parse_error",
            elapsed=elapsed,
            error=f"{type(exc).__name__}: {exc}",
        )
        return False

    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as fh:
        json.dump(doc.to_dict(), fh, indent=2)

    elapsed = time.monotonic() - started
    logger.info(
        "✓ %s → %s  (%d facts, %.2fs)",
        zip_path.name,
        output_path.name,
        len(doc.facts),
        elapsed,
    )

    log_run(
        log_dir,
        source_file=zip_path.name,
        status="success",
        elapsed=elapsed,
        facts_total=len(doc.facts),
        output_file=output_path.name,
    )
    return True


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------


def _process_directory(
    input_dir: Path,
    output_dir: Path,
    log_dir: Path,
    force: bool = False,
) -> int:
    """Process every *.zip in `input_dir`. Returns count of failures."""
    zips = sorted(input_dir.glob("*.zip"))
    if not zips:
        logger.warning("No .zip files found in %s", input_dir)
        return 0

    logger.info("Processing %d file(s) from %s", len(zips), input_dir)
    failures = 0
    for zip_path in zips:
        if not _process_one(zip_path, output_dir, log_dir, force=force):
            failures += 1

    logger.info("Done. %d succeeded, %d failed.", len(zips) - failures, failures)
    return failures


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m xbrl_extraction",
        description="Transform iXBRL filing zips into structured JSON.",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to a .zip file OR a directory containing .zip files.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        help=f"Where to write .facts.json files (default: {_DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=_DEFAULT_LOG_DIR,
        help=f"Where to write run_log.jsonl (default: {_DEFAULT_LOG_DIR})",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Re-extract zips even when their .facts.json already exists. "
        "Default behavior is to skip already-extracted files.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)

    input_path: Path = args.input

    if input_path.is_dir():
        failures = _process_directory(
            input_path,
            args.output_dir,
            args.log_dir,
            force=args.force,
        )
        return 0 if failures == 0 else 1

    if input_path.is_file() and input_path.suffix.lower() == ".zip":
        ok = _process_one(
            input_path,
            args.output_dir,
            args.log_dir,
            force=args.force,
        )
        return 0 if ok else 1

    logger.error("Input must be a .zip file or a directory: %s", input_path)
    return 2


if __name__ == "__main__":
    sys.exit(main())
