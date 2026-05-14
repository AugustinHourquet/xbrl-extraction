"""
parser.py — Low-level iXBRL parsing.

Reads raw iXBRL HTML and produces a `ParsedDocument` containing the three
orthogonal axes of an iXBRL filing:

  1. Facts    — every <ix:nonFraction> tag, with concept/value/context/unit
  2. Contexts — every <xbrli:context>, with period and dimension info
  3. Units    — every <xbrli:unit>, as simple measure or numerator/denominator

This module is intentionally generic. It does not know the output JSON
shape; `extractor.py` is responsible for turning a `ParsedDocument` into
a `schema.Document`. The split lets us swap the output format later
without touching the parser.

Non-numeric facts (`ix:nonNumeric`) are skipped — v1 is numeric-only by
design.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from xbrl_extraction.utils import clean_numeric

logger = logging.getLogger(__name__)

# bs4 warns when we point an HTML parser at XML-shaped content; the iXBRL
# document is HTML, but bs4 sees the xbrli:* tags and worries. We've
# chosen html.parser/lxml deliberately — silence the noise.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


# ---------------------------------------------------------------------------
# Intermediate dataclasses (parser-internal, not the output shape)
# ---------------------------------------------------------------------------


@dataclass
class ParsedContext:
    """An <xbrli:context> element, normalised."""

    id: str
    type: str  # "instant" | "duration"
    date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    dimensions: dict[str, str] = field(default_factory=dict)


@dataclass
class ParsedUnit:
    """An <xbrli:unit> element, normalised."""

    id: str
    measure: str | None = None
    numerator: str | None = None
    denominator: str | None = None


@dataclass
class ParsedFact:
    """An <ix:nonFraction> element, normalised."""

    concept: str
    value: float
    context_ref: str
    unit_ref: str
    decimals: str | None = None
    scale: str | None = None


@dataclass
class ParsedDocument:
    """Aggregate of everything we extract from the iXBRL htm."""

    facts: list[ParsedFact]
    contexts: dict[str, ParsedContext]
    units: dict[str, ParsedUnit]


# ---------------------------------------------------------------------------
# Context parsing
# ---------------------------------------------------------------------------


def _parse_contexts(soup: BeautifulSoup) -> dict[str, ParsedContext]:
    """
    Extract all <xbrli:context> elements.

    BeautifulSoup with the lxml backend lowercases namespaced tags, so we
    match against both `xbrli:context` and `context`. Same pattern applies
    to <period>/<instant>/<startDate>/<endDate>/<segment>.
    """
    contexts: dict[str, ParsedContext] = {}

    for ctx in soup.find_all(["xbrli:context", "context"]):
        ctx_id = ctx.get("id")
        if not ctx_id:
            continue

        ctx_obj = ParsedContext(id=ctx_id, type="")

        # ── Period ──────────────────────────────────────────────────────
        period = ctx.find(["xbrli:period", "period"])
        if period:
            instant = period.find(["xbrli:instant", "instant"])
            start = period.find(["xbrli:startdate", "startdate"])
            end = period.find(["xbrli:enddate", "enddate"])
            if instant:
                ctx_obj.type = "instant"
                ctx_obj.date = instant.get_text(strip=True)
            elif start and end:
                ctx_obj.type = "duration"
                ctx_obj.start_date = start.get_text(strip=True)
                ctx_obj.end_date = end.get_text(strip=True)

        if not ctx_obj.type:
            # Malformed context with no parseable period — skip
            continue

        # ── Dimensions (explicit members in <xbrli:segment>) ────────────
        segment = ctx.find(["xbrli:segment", "segment"])
        if segment:
            for member in segment.find_all(True):
                dim = member.get("dimension")
                if dim:
                    ctx_obj.dimensions[dim] = member.get_text(strip=True)

        contexts[ctx_id] = ctx_obj

    return contexts


# ---------------------------------------------------------------------------
# Unit parsing
# ---------------------------------------------------------------------------


def _parse_units(soup: BeautifulSoup) -> dict[str, ParsedUnit]:
    """
    Extract all <xbrli:unit> elements.

    Two shapes in the wild:
      <unit id="usd">
        <measure>iso4217:USD</measure>
      </unit>

      <unit id="usdPerShare">
        <divide>
          <unitNumerator><measure>iso4217:USD</measure></unitNumerator>
          <unitDenominator><measure>xbrli:shares</measure></unitDenominator>
        </divide>
      </unit>
    """
    units: dict[str, ParsedUnit] = {}

    for unit_el in soup.find_all(["xbrli:unit", "unit"]):
        unit_id = unit_el.get("id")
        if not unit_id:
            continue

        unit_obj = ParsedUnit(id=unit_id)

        divide = unit_el.find(["xbrli:divide", "divide"])
        if divide:
            num = divide.find(["xbrli:unitnumerator", "unitnumerator"])
            den = divide.find(["xbrli:unitdenominator", "unitdenominator"])
            if num:
                num_measure = num.find(["xbrli:measure", "measure"])
                if num_measure:
                    unit_obj.numerator = num_measure.get_text(strip=True)
            if den:
                den_measure = den.find(["xbrli:measure", "measure"])
                if den_measure:
                    unit_obj.denominator = den_measure.get_text(strip=True)
        else:
            measure = unit_el.find(["xbrli:measure", "measure"])
            if measure:
                unit_obj.measure = measure.get_text(strip=True)

        # Only keep units we could actually parse
        if unit_obj.measure or (unit_obj.numerator and unit_obj.denominator):
            units[unit_id] = unit_obj

    return units


# ---------------------------------------------------------------------------
# Fact parsing
# ---------------------------------------------------------------------------


def _parse_facts(soup: BeautifulSoup) -> list[ParsedFact]:
    """
    Extract every <ix:nonFraction> as a ParsedFact.

    Skips <ix:nonNumeric> entirely (textual disclosures — not in scope
    for v1; see the README design notes).

    A fact appearing multiple times in the source — once in the main
    statements, again in the notes — produces duplicate iXBRL tags with
    the same `name` + `contextRef`. We keep the first occurrence; later
    duplicates are dropped to avoid bloating the JSON.
    """
    facts: list[ParsedFact] = []
    seen: set[tuple[str, str]] = set()

    nonfraction_tags = soup.find_all(
        lambda tag: tag.name and tag.name.lower() in ("ix:nonfraction", "nonfraction")
    )

    for tag in nonfraction_tags:
        concept = tag.get("name")
        context_ref = tag.get("contextref")
        unit_ref = tag.get("unitref")

        if not (concept and context_ref and unit_ref):
            continue

        key = (concept, context_ref)
        if key in seen:
            continue

        value = clean_numeric(tag.get_text())
        if value is None:
            continue

        # iXBRL `sign` attribute: if "-", the displayed value is positive
        # but represents a negative number. Apply before storage.
        if tag.get("sign") == "-":
            value = -abs(value)

        facts.append(
            ParsedFact(
                concept=concept,
                value=value,
                context_ref=context_ref,
                unit_ref=unit_ref,
                decimals=tag.get("decimals"),
                scale=tag.get("scale"),
            )
        )
        seen.add(key)

    return facts


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_ixbrl(htm_content: str) -> ParsedDocument:
    """
    Parse an iXBRL HTML document into facts, contexts, and units.

    The returned `ParsedDocument` is a faithful structural transcription
    of the source — no filtering, no canonical naming, no scale
    normalisation. Higher-level interpretation is the extractor's job.
    """
    soup = BeautifulSoup(htm_content, "lxml")

    contexts = _parse_contexts(soup)
    units = _parse_units(soup)
    facts = _parse_facts(soup)

    logger.info(
        "Parsed iXBRL: %d facts, %d contexts, %d units",
        len(facts),
        len(contexts),
        len(units),
    )

    return ParsedDocument(facts=facts, contexts=contexts, units=units)
