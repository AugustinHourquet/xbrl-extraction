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

    Facts, periods, and units are the v1 payload — what gets serialised
    to `<basename>.facts.json`. The four `calc` / `pres` / `labs` /
    `defs` fields are optional in-memory attachments populated by
    `attach_*()` or `load_all()`. They are NOT included in `to_dict()`
    output — each linkbase has its own JSON file on disk.

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
        """Serialize to a JSON-compatible dict (facts.json shape only).

        Attached linkbases are deliberately excluded — they have their
        own files. Round-trip discipline: load(to_dict()) preserves the
        facts payload.
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
        the JSON shape. Attached linkbases default to None — use
        `attach_*` or `load_all` to populate them."""
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
    def load(cls, path) -> Document:
        """Load a .facts.json file from disk. Returns a Document with
        no linkbases attached — call `attach_*` or use `load_all`."""
        import json as _json
        from pathlib import Path as _Path

        with open(_Path(path)) as fh:
            return cls.from_dict(_json.load(fh))

    @classmethod
    def load_all(cls, facts_path, quiet: bool = False) -> Document:
        """Load `<basename>.facts.json` and auto-attach any sibling
        `<basename>.calc.json` / `.pres.json` / `.labs.json` / `.defs.json`
        files in the same directory.

        Missing siblings log a warning unless `quiet=True`. Never errors
        on missing siblings — only on a missing facts file or bad JSON.
        """
        import logging as _logging
        from pathlib import Path as _Path

        _logger = _logging.getLogger(__name__)

        facts_path = _Path(facts_path)
        doc = cls.load(facts_path)

        # Derive `<basename>` by stripping `.facts` from the stem.
        stem = facts_path.stem  # e.g. "aapl-2025.facts" → "aapl-2025.facts"
        if stem.endswith(".facts"):
            base = stem[: -len(".facts")]
        else:
            base = stem
        parent = facts_path.parent

        for kind, attach in (
            ("calc", doc.attach_calc),
            ("pres", doc.attach_pres),
            ("labs", doc.attach_labs),
            ("defs", doc.attach_defs),
        ):
            sibling = parent / f"{base}.{kind}.json"
            if sibling.exists():
                attach(sibling)
            elif not quiet:
                _logger.warning(
                    "load_all: sibling %s not found; skipping %s.",
                    sibling.name,
                    kind,
                )

        return doc

    # ── Linkbase attachment ────────────────────────────────────────

    def attach_calc(self, path) -> Document:
        """Attach a .calc.json. Returns self for chaining."""
        from xbrl_extraction.linkbases import Calculations

        self.calc = Calculations.load(path)
        return self

    def attach_pres(self, path) -> Document:
        from xbrl_extraction.linkbases import Presentation

        self.pres = Presentation.load(path)
        return self

    def attach_labs(self, path) -> Document:
        from xbrl_extraction.linkbases import Labels

        self.labs = Labels.load(path)
        return self

    def attach_defs(self, path) -> Document:
        from xbrl_extraction.linkbases import Definitions

        self.defs = Definitions.load(path)
        return self
