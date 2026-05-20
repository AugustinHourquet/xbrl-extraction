"""
schema.py — Dataclasses describing the output JSON shape.

A `Document` is the top-level container produced by `extractor.extract()`.
It serializes to the "facts" section of the combined filing JSON written
under data/output/<basename>.json.

The "facts" section shape:

    {
      "filing":  Filing,
      "periods": {context_id: Period},
      "units":   {unit_id: Unit},
      "facts":   [Fact, ...]
    }
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

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
    """
    Top-level container. Produced by `extractor.extract()` and consumed
    by `handlers.py`.

    Facts, periods, and units are the core payload. The four `calc` /
    `pres` / `labs` / `defs` fields hold the linkbases, populated by
    `Document.load(path)` from the combined filing JSON. They are NOT
    included in `to_dict()` — which serialises the facts section only.

    Filtering and operational methods live in `handlers.py` and are
    bound onto this class at import time. See that module's docstring.
    """

    filing: Filing
    periods: dict[str, Period]
    units: dict[str, Unit]
    facts: list[Fact]

    # v2 — optional attached linkbases. Imported lazily inside methods
    # to avoid an import cycle with linkbases.py / handlers.py.
    calc: Any | None = None
    pres: Any | None = None
    labs: Any | None = None
    defs: Any | None = None

    # ── Serialisation ──────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize the facts section to a JSON-compatible dict.

        Linkbases are deliberately excluded — the combined output file
        is assembled by the CLI. Round-trip: Document.from_dict(to_dict())
        preserves the facts payload.
        """
        return {
            "filing": asdict(self.filing),
            "periods": {k: v.to_dict() for k, v in self.periods.items()},
            "units": {k: v.to_dict() for k, v in self.units.items()},
            "facts": [f.to_dict() for f in self.facts],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Document:
        """Inverse of `to_dict`. Reconstructs facts/periods/units from
        the facts-section JSON shape. Linkbases default to None."""
        filing = Filing(**d["filing"])

        periods: dict[str, Period] = {}
        for k, v in d.get("periods", {}).items():
            periods[k] = Period(
                type=v["type"],
                date=v.get("date"),
                start=v.get("start"),
                end=v.get("end"),
            )

        units: dict[str, Unit] = {}
        for k, v in d.get("units", {}).items():
            units[k] = Unit(
                measure=v.get("measure"),
                numerator=v.get("numerator"),
                denominator=v.get("denominator"),
            )

        facts: list[Fact] = []
        for fd in d.get("facts", []):
            facts.append(
                Fact(
                    concept=fd["concept"],
                    value=fd["value"],
                    unit=fd["unit"],
                    period=fd["period"],
                    decimals=fd.get("decimals"),
                    scale=fd.get("scale"),
                    dimensions=fd.get("dimensions", {}) or {},
                )
            )

        return cls(filing=filing, periods=periods, units=units, facts=facts)

    @classmethod
    def load(cls, path, *, linkbases: bool = True) -> Document:
        """Load a combined filing JSON from disk.

        With `linkbases=True` (default) all four linkbase sections are
        attached when present. Pass `linkbases=False` to load facts only.
        """
        import json as _json
        from pathlib import Path as _Path

        from xbrl_extraction.linkbases import Calculations, Definitions, Labels, Presentation

        with open(_Path(path)) as fh:
            data = _json.load(fh)

        doc = cls.from_dict(data["facts"])

        if linkbases:
            if "calc" in data:
                doc.calc = Calculations.from_dict(data["calc"])
            if "pres" in data:
                doc.pres = Presentation.from_dict(data["pres"])
            if "labs" in data:
                doc.labs = Labels.from_dict(data["labs"])
            if "defs" in data:
                doc.defs = Definitions.from_dict(data["defs"])

        return doc
