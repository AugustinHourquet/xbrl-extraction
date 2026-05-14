"""
schema.py — Dataclasses describing the output JSON shape.

A `Document` is the top-level container produced by `extractor.extract()`.
It serializes to the JSON written under data/output/<basename>.facts.json.

The shape:

    {
      "filing":  Filing,
      "periods": {context_id: Period},
      "units":   {unit_id: Unit},
      "facts":   [Fact, ...]
    }
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# ---------------------------------------------------------------------------
# Filing metadata
# ---------------------------------------------------------------------------


@dataclass
class Filing:
    """
    Filing-level metadata. All fields come from `dei:` facts in the iXBRL
    document itself, or are sniffed from the zip / namespaces. No external
    enrichment — entity metadata (name, ticker, CIK) is intentionally out
    of scope for v1.
    """

    form: str | None  # e.g. "10-K"   ← dei:DocumentType
    fiscal_year: int | None  # e.g. 2025      ← dei:DocumentFiscalYearFocus
    fiscal_period: str | None  # e.g. "FY"      ← dei:DocumentFiscalPeriodFocus
    period_end: str | None  # ISO date       ← FY duration end_date
    accounting_standard: str | None  # "US-GAAP" | "IFRS" | None
    source_file: str  # input zip basename
    primary_document: str  # iXBRL .htm filename inside the zip


# ---------------------------------------------------------------------------
# Period (context-derived)
# ---------------------------------------------------------------------------


@dataclass
class Period:
    """
    A reporting period, derived from an <xbrli:context>.

    type='instant'  → only `date` is set    (balance-sheet snapshots)
    type='duration' → `start` and `end` are set (P&L, cash flow)

    Keyed in the `periods` dict by the raw `contextRef` from the filing
    (e.g. "c-1", "c-12") so facts can round-trip back to the source.
    """

    type: str  # "instant" | "duration"
    date: str | None = None  # ISO date, instant only
    start: str | None = None  # ISO date, duration only
    end: str | None = None  # ISO date, duration only

    def to_dict(self) -> dict:
        d = {"type": self.type}
        if self.type == "instant":
            d["date"] = self.date
        else:
            d["start"] = self.start
            d["end"] = self.end
        return d


# ---------------------------------------------------------------------------
# Unit (xbrli:unit-derived)
# ---------------------------------------------------------------------------


@dataclass
class Unit:
    """
    A unit of measure, derived from an <xbrli:unit>.

    Two shapes:
      - Simple measure:    {"measure": "iso4217:USD"}
      - Divide (rate):     {"numerator": "iso4217:USD",
                            "denominator": "xbrli:shares"}

    Keyed in the `units` dict by the raw unit id from the filing
    (e.g. "usd", "shares", "usdPerShare").
    """

    measure: str | None = None
    numerator: str | None = None
    denominator: str | None = None

    def to_dict(self) -> dict:
        if self.numerator and self.denominator:
            return {"numerator": self.numerator, "denominator": self.denominator}
        return {"measure": self.measure}


# ---------------------------------------------------------------------------
# Fact
# ---------------------------------------------------------------------------


@dataclass
class Fact:
    """
    A single iXBRL fact — one <ix:nonFraction> in the source document.

    `value` is preserved exactly as filed: if the source has `scale="6"` and
    text "307,003", the value here is 307003 (i.e. 307,003 million). The
    `scale` and `decimals` attributes are kept so consumers can interpret.

    `period` and `unit` are reference ids that point into the top-level
    `periods` and `units` dicts. They are intentionally not denormalised.

    `dimensions` only appears when non-empty — i.e. when the underlying
    context has an <xbrli:segment> with explicit dimension members
    (segment breakdowns, geography, product line, etc.).
    """

    concept: str  # e.g. "us-gaap:Assets"
    value: float  # numeric value as filed
    unit: str  # unit id, key into Document.units
    period: str  # context id, key into Document.periods
    decimals: str | None = None  # iXBRL `decimals` attr, as filed
    scale: str | None = None  # iXBRL `scale` attr, as filed
    dimensions: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "concept": self.concept,
            "value": self.value,
            "unit": self.unit,
            "period": self.period,
        }
        if self.decimals is not None:
            d["decimals"] = self.decimals
        if self.scale is not None:
            d["scale"] = self.scale
        if self.dimensions:
            d["dimensions"] = self.dimensions
        return d


# ---------------------------------------------------------------------------
# Document — top-level container
# ---------------------------------------------------------------------------


@dataclass
class Document:
    """Top-level container. Produced by `extractor.extract()`."""

    filing: Filing
    periods: dict[str, Period]
    units: dict[str, Unit]
    facts: list[Fact]

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return {
            "filing": asdict(self.filing),
            "periods": {k: v.to_dict() for k, v in self.periods.items()},
            "units": {k: v.to_dict() for k, v in self.units.items()},
            "facts": [f.to_dict() for f in self.facts],
        }
