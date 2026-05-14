"""
extractor.py — Orchestrates the zip-to-Document transform.

Public entry point: `extract(zip_path) -> Document`.

Responsibilities:
  1. Open the zip and locate the primary iXBRL .htm file
  2. Call `parser.parse_ixbrl()` to get the structural intermediate
  3. Sniff the accounting standard from concept namespaces
  4. Lift filing metadata from `dei:` facts and the FY context
  5. Assemble the final `schema.Document`

No GCS, no comparison, no canonical mapping — this module does one
thing: produce a faithful structured view of one filing.
"""

from __future__ import annotations

import logging
import zipfile
from collections import Counter
from pathlib import Path

from xbrl_extraction.parser import ParsedDocument, parse_ixbrl
from xbrl_extraction.schema import Document, Fact, Filing, Period, Unit
from xbrl_extraction.utils import find_primary_document, read_htm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Accounting standard detection
# ---------------------------------------------------------------------------

# Mapping from concept-namespace prefix to standard label. Order matters
# only for ties; in practice us-gaap and ifrs-full are mutually exclusive
# in a single filing.
_STANDARD_NAMESPACES = {
    "us-gaap": "US-GAAP",
    "ifrs-full": "IFRS",
}


def _detect_accounting_standard(parsed: ParsedDocument) -> str | None:
    """
    Identify the accounting standard by counting concept namespace
    prefixes in the parsed facts. Returns the standard with the most
    facts, or None if no recognised standard namespace is dominant.
    """
    prefix_counts: Counter[str] = Counter()
    for fact in parsed.facts:
        prefix = fact.concept.split(":", 1)[0] if ":" in fact.concept else ""
        if prefix in _STANDARD_NAMESPACES:
            prefix_counts[prefix] += 1

    if not prefix_counts:
        logger.warning("No recognised accounting standard namespace found.")
        return None

    top_prefix, count = prefix_counts.most_common(1)[0]
    logger.debug("Accounting standard: %s (%d facts)", _STANDARD_NAMESPACES[top_prefix], count)
    return _STANDARD_NAMESPACES[top_prefix]


# ---------------------------------------------------------------------------
# Filing metadata extraction
# ---------------------------------------------------------------------------


def _find_dei_fact_text(parsed: ParsedDocument, concept: str) -> str | None:
    """
    Find a dei:* fact value. Used for fields with simple text content
    (DocumentType="10-K", DocumentFiscalPeriodFocus="FY").

    Note: parser stores values as floats — fine for numeric dei facts
    like DocumentFiscalYearFocus (2025 → 2025.0) but useless for string
    ones like DocumentType. For those we need to read the htm again at
    the extractor level.
    """
    # This path handles numeric dei facts only; string ones go via the
    # extractor's separate raw-text lookup in `_extract_filing_metadata`.
    for fact in parsed.facts:
        if fact.concept == concept:
            return str(fact.value)
    return None


def _extract_dei_strings(htm_content: str) -> dict[str, str]:
    """
    Extract the text content of key dei:* string facts directly from
    the htm, since the numeric parser skips them. We look for both
    ix:nonNumeric and ix:nonFraction (DocumentFiscalYearFocus is
    technically nonFraction with no unit).

    Returns a flat dict {concept_local_name: text_value}.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(htm_content, "lxml")

    wanted = {
        "dei:DocumentType",
        "dei:DocumentFiscalYearFocus",
        "dei:DocumentFiscalPeriodFocus",
        "dei:DocumentPeriodEndDate",
    }
    result: dict[str, str] = {}

    for tag in soup.find_all(["ix:nonnumeric", "nonnumeric", "ix:nonfraction", "nonfraction"]):
        name = tag.get("name")
        if name in wanted and name not in result:
            # For ixt-formatted facts the displayed text differs from
            # the underlying ISO value. We keep the displayed text for
            # DocumentType/FiscalYearFocus/FiscalPeriodFocus (always
            # plain) and fall back to context dates for period_end.
            result[name] = tag.get_text(strip=True)

    return result


def _resolve_period_end(
    parsed: ParsedDocument,
    fiscal_year_focus: str | None,
) -> str | None:
    """
    Determine the filing's fiscal year-end date.

    Priority:
      1. The end_date of the longest duration context whose end year
         matches DocumentFiscalYearFocus (this is the FY context).
      2. The most common instant date among non-dimensional contexts
         (the balance-sheet date).
      3. None.

    Reading from contexts rather than dei:DocumentPeriodEndDate avoids
    the ixt-format transform-parsing problem (e.g. "September 27, 2025"
    needs custom parsing to become "2025-09-27").
    """
    # Strategy 1: longest duration ending in FY focus year
    if fiscal_year_focus:
        fy_durations = [
            c
            for c in parsed.contexts.values()
            if c.type == "duration"
            and c.end_date
            and c.end_date.startswith(fiscal_year_focus)
            and not c.dimensions
        ]
        if fy_durations:
            # The full-year context is the one with the earliest start_date
            # (i.e. ~12 months before end_date), not just any duration
            # ending in the year.
            fy_durations.sort(key=lambda c: c.start_date or "")
            return fy_durations[0].end_date

    # Strategy 2: most common non-dimensional instant
    instant_dates = Counter(
        c.date
        for c in parsed.contexts.values()
        if c.type == "instant" and c.date and not c.dimensions
    )
    if instant_dates:
        return instant_dates.most_common(1)[0][0]

    return None


def _extract_filing_metadata(
    parsed: ParsedDocument,
    htm_content: str,
    source_file: str,
    primary_document: str,
) -> Filing:
    """Assemble the Filing block from dei facts and context inspection."""
    dei = _extract_dei_strings(htm_content)

    fiscal_year_str = dei.get("dei:DocumentFiscalYearFocus")
    try:
        fiscal_year = int(fiscal_year_str) if fiscal_year_str else None
    except ValueError:
        logger.warning("Could not parse fiscal year: %r", fiscal_year_str)
        fiscal_year = None

    return Filing(
        form=dei.get("dei:DocumentType"),
        fiscal_year=fiscal_year,
        fiscal_period=dei.get("dei:DocumentFiscalPeriodFocus"),
        period_end=_resolve_period_end(parsed, fiscal_year_str),
        accounting_standard=_detect_accounting_standard(parsed),
        source_file=source_file,
        primary_document=primary_document,
    )


# ---------------------------------------------------------------------------
# Shape conversion: ParsedDocument → Document
# ---------------------------------------------------------------------------


def _build_periods(parsed: ParsedDocument) -> dict[str, Period]:
    """Convert ParsedContext → Period, keeping only contexts referenced
    by at least one fact. Reduces JSON size; an unreferenced context
    is dead weight."""
    referenced = {f.context_ref for f in parsed.facts}
    out: dict[str, Period] = {}
    for ctx_id in referenced:
        ctx = parsed.contexts.get(ctx_id)
        if ctx is None:
            continue
        out[ctx_id] = Period(
            type=ctx.type,
            date=ctx.date,
            start=ctx.start_date,
            end=ctx.end_date,
        )
    return out


def _build_units(parsed: ParsedDocument) -> dict[str, Unit]:
    """Convert ParsedUnit → Unit, keeping only units referenced by at
    least one fact."""
    referenced = {f.unit_ref for f in parsed.facts}
    out: dict[str, Unit] = {}
    for unit_id in referenced:
        u = parsed.units.get(unit_id)
        if u is None:
            continue
        out[unit_id] = Unit(
            measure=u.measure,
            numerator=u.numerator,
            denominator=u.denominator,
        )
    return out


def _build_facts(parsed: ParsedDocument) -> list[Fact]:
    """Convert ParsedFact → Fact, attaching dimensions from the
    underlying context."""
    out: list[Fact] = []
    for pf in parsed.facts:
        ctx = parsed.contexts.get(pf.context_ref)
        dims = ctx.dimensions if ctx else {}
        out.append(
            Fact(
                concept=pf.concept,
                value=pf.value,
                unit=pf.unit_ref,
                period=pf.context_ref,
                decimals=pf.decimals,
                scale=pf.scale,
                dimensions=dims,
            )
        )
    # Sort for human-readable JSON: by concept, then period id
    out.sort(key=lambda f: (f.concept, f.period))
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract(zip_path: str | Path) -> Document:
    """
    Extract a single iXBRL filing zip into a structured Document.

    Raises:
        FileNotFoundError if the zip doesn't exist.
        ValueError       if no iXBRL document can be located inside.
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(f"Zip not found: {zip_path}")

    logger.info("Opening %s", zip_path.name)

    with zipfile.ZipFile(zip_path) as zf:
        primary = find_primary_document(zf)
        if primary is None:
            raise ValueError(f"No iXBRL document found in {zip_path.name}")

        logger.info("Primary document: %s", primary)
        htm_content = read_htm(zf, primary)

    parsed = parse_ixbrl(htm_content)

    filing = _extract_filing_metadata(
        parsed,
        htm_content,
        source_file=zip_path.name,
        primary_document=primary,
    )

    return Document(
        filing=filing,
        periods=_build_periods(parsed),
        units=_build_units(parsed),
        facts=_build_facts(parsed),
    )
