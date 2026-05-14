"""
scripts/inspect_filings.py — Inspect extracted filings from the command line.

Resolves filings by company ID (e.g. "1860" → Apple) by globbing
data/output/ for facts.json files matching `*_<id>_*.facts.json`. When
a company has filings across multiple years, the most recent is picked
unless --year is given.

Four subcommands:

    summary    — print doc.summary()
    statements — list role_short values from pres with their role_definition
    render     — print doc.render_statement(role, date)
    verify     — print doc.verify(role, date, tolerance) as a table

Examples:
    python scripts/inspect_filings.py summary --file 1860
    python scripts/inspect_filings.py statements --file 1860
    python scripts/inspect_filings.py render  --file 1860 --role CONSOLIDATEDBALANCESHEETS
    python scripts/inspect_filings.py verify  --file 1860 --role CONSOLIDATEDBALANCESHEETS

`--date` defaults to the filing's own period_end (the FY end date),
which is what you want 99% of the time. Pass `--date YYYY-MM-DD` to
target a different period that exists in the filing.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from xbrl_extraction import Document

# ---------------------------------------------------------------------------
# File resolution: company ID → facts.json path
# ---------------------------------------------------------------------------

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT = _PACKAGE_ROOT / "data" / "output"

# Filenames look like: rawdata_us_1860_1860_XBRL_2025-09-27.facts.json
# Extract the ID (any digits between underscores) and the date suffix.
_FACTS_RE = re.compile(
    r"(?P<prefix>[^/\\]*?)_(?P<id1>\d+)_(?P<id2>\d+)_XBRL_(?P<date>\d{4}-\d{2}-\d{2})\.facts\.json$"
)


def resolve_facts_path(
    company_id: str,
    year: str | None = None,
    output_dir: Path = _DEFAULT_OUTPUT,
) -> Path:
    """Locate the facts.json for a given company ID.

    Matches files where either the first or second numeric segment
    in the filename equals `company_id`. When multiple match, returns
    the most recent by date suffix unless `year` is given.

    Raises FileNotFoundError if no facts.json matches.
    """
    if not output_dir.is_dir():
        raise FileNotFoundError(
            f"Output directory does not exist: {output_dir}\n"
            f"Run `python -m xbrl_extraction data/input/` first."
        )

    matches: list[tuple[Path, str]] = []
    for path in output_dir.glob("*.facts.json"):
        m = _FACTS_RE.search(path.name)
        if not m:
            continue
        if company_id in (m.group("id1"), m.group("id2")):
            if year is None or m.group("date").startswith(year):
                matches.append((path, m.group("date")))

    if not matches:
        suffix = f" for year {year}" if year else ""
        raise FileNotFoundError(
            f"No facts.json found for company ID {company_id!r}{suffix} "
            f"in {output_dir}.\n"
            f"Available IDs: {sorted(_list_known_ids(output_dir))}"
        )

    # Most recent first
    matches.sort(key=lambda t: t[1], reverse=True)
    chosen, _date = matches[0]

    if len(matches) > 1 and year is None:
        print(
            f"[note] Multiple filings for company {company_id}; using most recent "
            f"({chosen.name}). Pass --year to disambiguate.",
            file=sys.stderr,
        )

    return chosen


def _list_known_ids(output_dir: Path) -> set[str]:
    ids: set[str] = set()
    for path in output_dir.glob("*.facts.json"):
        m = _FACTS_RE.search(path.name)
        if m:
            ids.add(m.group("id1"))
    return ids


def _load(args) -> Document:
    """Resolve company ID → Document with linkbases auto-attached."""
    facts_path = resolve_facts_path(args.file, year=args.year)
    return Document.load_all(facts_path, quiet=True)


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------


def cmd_summary(args) -> int:
    doc = _load(args)
    print(doc.summary())
    return 0


# ---------------------------------------------------------------------------
# statements — list role_shorts available in this filing
# ---------------------------------------------------------------------------


def cmd_statements(args) -> int:
    doc = _load(args)
    if doc.pres is None:
        print("Presentation linkbase not available — cannot list statements.", file=sys.stderr)
        return 2

    # Group by role; pick the first non-empty role_definition we see.
    by_role: dict[str, str] = {}
    counts: dict[str, int] = {}
    for arc in doc.pres.arcs:
        by_role.setdefault(arc.role_short, arc.role_definition or "")
        counts[arc.role_short] = counts.get(arc.role_short, 0) + 1

    # Width for alignment
    max_short = max((len(s) for s in by_role), default=20)
    print(f"{'role_short'.ljust(max_short)}   arcs   role_definition")
    print(f"{'-' * max_short}   ----   ---------------")
    for short in sorted(by_role):
        defn = by_role[short] or "(no definition)"
        print(f"{short.ljust(max_short)}   {counts[short]:>4}   {defn}")
    return 0


# ---------------------------------------------------------------------------
# render — print a statement
# ---------------------------------------------------------------------------


def cmd_render(args) -> int:
    doc = _load(args)
    date = args.date or doc.filing.period_end
    if not date:
        print(
            "No --date given and filing has no period_end. Pass --date YYYY-MM-DD.", file=sys.stderr
        )
        return 2
    try:
        print(doc.render_statement(role_short=args.role, period_end=date))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("\nAvailable statements:", file=sys.stderr)
        print(
            "  Run: python scripts/inspect_filings.py statements --file " f"{args.file}",
            file=sys.stderr,
        )
        return 2
    return 0


# ---------------------------------------------------------------------------
# verify — print the verify dataframe
# ---------------------------------------------------------------------------


def cmd_verify(args) -> int:
    doc = _load(args)
    date = args.date or doc.filing.period_end
    if not date:
        print(
            "No --date given and filing has no period_end. Pass --date YYYY-MM-DD.", file=sys.stderr
        )
        return 2

    df = doc.verify(
        role_short=args.role,
        period_end=date,
        tolerance=args.tolerance,
    )
    if df.empty:
        print(f"No calc rules found for role {args.role!r}.", file=sys.stderr)
        return 2

    # Print full table (pandas would truncate columns by default)
    import pandas as pd

    with pd.option_context(
        "display.max_rows",
        None,
        "display.max_columns",
        None,
        "display.width",
        160,
        "display.max_colwidth",
        60,
    ):
        print(df.to_string(index=False))

    # Tail summary
    counts = df["status"].value_counts().to_dict()
    print()
    print("Status counts:", "  ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


# ---------------------------------------------------------------------------
# argparse plumbing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/inspect_filings.py",
        description="Inspect extracted XBRL filings from the CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Shared args: every subcommand takes --file (company id) and --year.
    def add_filing_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--file",
            required=True,
            help="Company ID (e.g. 1860 for Apple). Matched against the "
            "numeric segments of facts.json filenames.",
        )
        sp.add_argument(
            "--year",
            default=None,
            help="Fiscal year (e.g. 2025) to disambiguate when a company "
            "has multiple filings. Default: most recent.",
        )

    p_summary = subparsers.add_parser("summary", help="Print a one-page overview of the filing.")
    add_filing_args(p_summary)
    p_summary.set_defaults(func=cmd_summary)

    p_stmts = subparsers.add_parser(
        "statements", help="List available statements (role_short values) in this filing."
    )
    add_filing_args(p_stmts)
    p_stmts.set_defaults(func=cmd_statements)

    p_render = subparsers.add_parser(
        "render", help="Render a single statement to stdout as indented text."
    )
    add_filing_args(p_render)
    p_render.add_argument(
        "--role",
        required=True,
        help="role_short of the statement (use the `statements` subcommand to list).",
    )
    p_render.add_argument(
        "--date", default=None, help="Period end date YYYY-MM-DD. Default: filing's period_end."
    )
    p_render.set_defaults(func=cmd_render)

    p_verify = subparsers.add_parser(
        "verify", help="Verify calc arithmetic against actual facts for a statement."
    )
    add_filing_args(p_verify)
    p_verify.add_argument("--role", required=True, help="role_short of the statement to verify.")
    p_verify.add_argument(
        "--date", default=None, help="Period end date YYYY-MM-DD. Default: filing's period_end."
    )
    p_verify.add_argument(
        "--tolerance",
        type=float,
        default=0.0,
        help="Acceptable absolute difference (default 0.0 = strict). "
        "Pass e.g. 1.0 to dismiss filer rounding to the nearest million.",
    )
    p_verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
