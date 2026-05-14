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

Idempotency: by default, a zip is skipped when all five output JSONs
exist. Pass --force to re-extract everything (e.g. after an extractor
bug fix). Skipped files do NOT produce a run_log.jsonl record.

By default the CLI emits five files per zip (facts + calc/pres/labs/defs).
Pass --facts-only to emit just facts.json — useful when you only need
the raw fact data and don't want to wait for linkbase parsing.

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


def _output_paths_for(zip_path: Path, output_dir: Path) -> dict[str, Path]:
    """Map output kind → path for one input zip.

    Returns a dict keyed by short kind name ('facts', 'calc', 'pres',
    'labs', 'defs'). All five paths share the basename derived from the
    input zip stem.

      data/input/foo.zip → {
        'facts': data/output/foo.facts.json,
        'calc':  data/output/foo.calc.json,
        ...
      }
    """
    stem = zip_path.stem
    return {
        "facts": output_dir / f"{stem}.facts.json",
        "calc": output_dir / f"{stem}.calc.json",
        "pres": output_dir / f"{stem}.pres.json",
        "labs": output_dir / f"{stem}.labs.json",
        "defs": output_dir / f"{stem}.defs.json",
    }


# ---------------------------------------------------------------------------
# Single-file processing
# ---------------------------------------------------------------------------


def _process_one(
    zip_path: Path,
    output_dir: Path,
    log_dir: Path,
    force: bool = False,
    facts_only: bool = False,
) -> bool:
    """
    Extract one zip and write the output JSON(s). Returns True on success OR skip.

    Idempotency:
      - Default mode: skip when ALL five output files already exist.
      - facts_only mode: skip when just .facts.json exists.
    Missing any → regenerate (ensures consistent state). Pass
    force=True to re-extract regardless.

    facts_only mode still parses everything (extraction is single-pass),
    it just doesn't write the four linkbase JSONs. The runtime saving
    is modest; the main use case is keeping output/ uncluttered when
    you only care about the raw fact data.

    All exceptions are caught and turned into a run-log record; the
    caller decides whether to keep going with the next file.
    """
    paths = _output_paths_for(zip_path, output_dir)

    # Idempotency check — different file set depending on facts_only
    required = [paths["facts"]] if facts_only else list(paths.values())
    if not force and all(p.exists() for p in required):
        suffix = " (facts only)" if facts_only else ""
        logger.info(
            "⊘ %s → already extracted%s (use --force to re-run)",
            zip_path.name,
            suffix,
        )
        return True

    started = time.monotonic()

    try:
        result = extract(zip_path)
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

    # Always emit facts.json
    with open(paths["facts"], "w") as fh:
        json.dump(result.document.to_dict(), fh, indent=2)

    # Linkbase outputs — written only when not facts_only AND the
    # extractor produced them.
    counts = {
        "calc_edges": 0,
        "pres_edges": 0,
        "labs_count": 0,
        "defs_edges": 0,
    }
    output_files = [paths["facts"].name]

    if not facts_only:
        if result.calc is not None:
            with open(paths["calc"], "w") as fh:
                json.dump(result.calc.to_dict(), fh, indent=2)
            counts["calc_edges"] = len(result.calc.arcs)
            output_files.append(paths["calc"].name)

        if result.presentation is not None:
            with open(paths["pres"], "w") as fh:
                json.dump(result.presentation.to_dict(), fh, indent=2)
            counts["pres_edges"] = len(result.presentation.arcs)
            output_files.append(paths["pres"].name)

        if result.labels is not None:
            with open(paths["labs"], "w") as fh:
                json.dump(result.labels.to_dict(), fh, indent=2)
            counts["labs_count"] = len(result.labels.entries)
            output_files.append(paths["labs"].name)

        if result.definitions is not None:
            with open(paths["defs"], "w") as fh:
                json.dump(result.definitions.to_dict(), fh, indent=2)
            counts["defs_edges"] = len(result.definitions.arcs)
            output_files.append(paths["defs"].name)

    elapsed = time.monotonic() - started
    if facts_only:
        logger.info(
            "✓ %s  (%d facts, facts-only, %.2fs)",
            zip_path.name,
            len(result.document.facts),
            elapsed,
        )
    else:
        logger.info(
            "✓ %s  (%d facts, calc=%d, pres=%d, labs=%d, defs=%d, %.2fs)",
            zip_path.name,
            len(result.document.facts),
            counts["calc_edges"],
            counts["pres_edges"],
            counts["labs_count"],
            counts["defs_edges"],
            elapsed,
        )

    log_run(
        log_dir,
        source_file=zip_path.name,
        status="success",
        elapsed=elapsed,
        facts_total=len(result.document.facts),
        output_files=output_files,
        **counts,
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
    facts_only: bool = False,
) -> int:
    """Process every *.zip in `input_dir`. Returns count of failures."""
    zips = sorted(input_dir.glob("*.zip"))
    if not zips:
        logger.warning("No .zip files found in %s", input_dir)
        return 0

    logger.info("Processing %d file(s) from %s", len(zips), input_dir)
    failures = 0
    for zip_path in zips:
        if not _process_one(zip_path, output_dir, log_dir, force=force, facts_only=facts_only):
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
        help="Re-extract zips even when their output files already exist. "
        "Default behavior is to skip already-extracted files.",
    )
    parser.add_argument(
        "--facts-only",
        action="store_true",
        help="Emit only .facts.json; skip writing the four linkbase JSONs "
        "(.calc / .pres / .labs / .defs). Idempotency checks against "
        "facts.json alone in this mode.",
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
            facts_only=args.facts_only,
        )
        return 0 if failures == 0 else 1

    if input_path.is_file() and input_path.suffix.lower() == ".zip":
        ok = _process_one(
            input_path,
            args.output_dir,
            args.log_dir,
            force=args.force,
            facts_only=args.facts_only,
        )
        return 0 if ok else 1

    logger.error("Input must be a .zip file or a directory: %s", input_path)
    return 2


if __name__ == "__main__":
    sys.exit(main())
