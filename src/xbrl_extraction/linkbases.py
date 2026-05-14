"""
linkbases.py — Dataclasses for the four linkbase output files.

Each container mirrors one of the .calc.json / .pres.json / .labs.json /
.defs.json files written by the parsers. They are deserialised back into
these classes by `.load()` for use in `handlers.Document`.

Design rule: containers are dumb. They store data and offer `.load()` and
`.to_dict()`. Operations (tree-walking, filtering, label lookup) live on
`Document`, not here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Calculation linkbase
# ---------------------------------------------------------------------------


@dataclass
class CalcArc:
    """One calculation arc: parent = parent + (weight × child)."""

    role: str
    role_short: str
    parent: str
    child: str
    weight: float
    order: float

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "role_short": self.role_short,
            "parent": self.parent,
            "child": self.child,
            "weight": self.weight,
            "order": self.order,
        }


@dataclass
class Calculations:
    """All calc arcs in a filing, plus role definitions."""

    filing: dict
    arcs: list[CalcArc]
    role_definitions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "filing": self.filing,
            "role_definitions": self.role_definitions,
            "calculations": [a.to_dict() for a in self.arcs],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Calculations:
        return cls(
            filing=d.get("filing", {}),
            role_definitions=d.get("role_definitions", {}),
            arcs=[CalcArc(**a) for a in d.get("calculations", [])],
        )

    @classmethod
    def load(cls, path: str | Path) -> Calculations:
        with open(path) as fh:
            return cls.from_dict(json.load(fh))


# ---------------------------------------------------------------------------
# Presentation linkbase
# ---------------------------------------------------------------------------


@dataclass
class PresArc:
    """One presentation arc: child appears under parent in this role/statement."""

    role: str
    role_short: str
    role_definition: str
    parent: str
    child: str
    order: float
    preferred_label: str | None = None

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "role_short": self.role_short,
            "role_definition": self.role_definition,
            "parent": self.parent,
            "child": self.child,
            "order": self.order,
            "preferred_label": self.preferred_label,
        }


@dataclass
class Presentation:
    filing: dict
    arcs: list[PresArc]

    def to_dict(self) -> dict:
        return {
            "filing": self.filing,
            "presentation": [a.to_dict() for a in self.arcs],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Presentation:
        return cls(
            filing=d.get("filing", {}),
            arcs=[PresArc(**a) for a in d.get("presentation", [])],
        )

    @classmethod
    def load(cls, path: str | Path) -> Presentation:
        with open(path) as fh:
            return cls.from_dict(json.load(fh))


# ---------------------------------------------------------------------------
# Label linkbase
# ---------------------------------------------------------------------------


@dataclass
class LabelEntry:
    """One label record: a (concept, role, language) → text mapping."""

    concept: str
    label_role: str
    language: str
    text: str

    def to_dict(self) -> dict:
        return {
            "concept": self.concept,
            "label_role": self.label_role,
            "language": self.language,
            "text": self.text,
        }


@dataclass
class Labels:
    filing: dict
    entries: list[LabelEntry]

    # Constants for label-role URLs we look up most often
    STANDARD = "http://www.xbrl.org/2003/role/label"
    TERSE = "http://www.xbrl.org/2003/role/terseLabel"
    TOTAL = "http://www.xbrl.org/2003/role/totalLabel"

    def to_dict(self) -> dict:
        return {
            "filing": self.filing,
            "labels": [e.to_dict() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Labels:
        return cls(
            filing=d.get("filing", {}),
            entries=[LabelEntry(**e) for e in d.get("labels", [])],
        )

    @classmethod
    def load(cls, path: str | Path) -> Labels:
        with open(path) as fh:
            return cls.from_dict(json.load(fh))

    def get(
        self,
        concept: str,
        preferred_label: str | None = None,
        language: str = "en-US",
    ) -> str | None:
        """
        Best-effort label resolution.

        Strategy:
          1. If `preferred_label` is given, return that exact label-role
             variant (if it exists in the requested language).
          2. Else return the standardLabel.
          3. Else any label in the requested language.
          4. Else any label at all.
          5. Else None.
        """
        for_concept = [e for e in self.entries if e.concept == concept]
        if not for_concept:
            return None

        in_lang = [e for e in for_concept if e.language == language]

        if preferred_label:
            for e in in_lang or for_concept:
                if e.label_role == preferred_label:
                    return e.text

        for e in in_lang or for_concept:
            if e.label_role == self.STANDARD:
                return e.text

        if in_lang:
            return in_lang[0].text
        return for_concept[0].text


# ---------------------------------------------------------------------------
# Definition linkbase
# ---------------------------------------------------------------------------


@dataclass
class DefArc:
    """One definition arc: a dimensional relationship between concepts."""

    role: str
    role_short: str
    arc_role: str  # local name only — "hypercube-dimension", etc.
    from_: str  # `from` is reserved; trailing-underscore in code, "from" in JSON
    to: str
    order: float

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "role_short": self.role_short,
            "arc_role": self.arc_role,
            "from": self.from_,
            "to": self.to,
            "order": self.order,
        }


@dataclass
class Definitions:
    filing: dict
    arcs: list[DefArc]

    def to_dict(self) -> dict:
        return {
            "filing": self.filing,
            "definitions": [a.to_dict() for a in self.arcs],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Definitions:
        arcs = []
        for a in d.get("definitions", []):
            arcs.append(
                DefArc(
                    role=a["role"],
                    role_short=a["role_short"],
                    arc_role=a["arc_role"],
                    from_=a["from"],
                    to=a["to"],
                    order=a["order"],
                )
            )
        return cls(filing=d.get("filing", {}), arcs=arcs)

    @classmethod
    def load(cls, path: str | Path) -> Definitions:
        with open(path) as fh:
            return cls.from_dict(json.load(fh))
