# src/xbrl_extraction/schema.py
from dataclasses import dataclass, field


@dataclass
class Fact:
    concept: str
    label: str
    value: str | None
    unit: str | None
    period: str | None


@dataclass
class FilingResult:
    entity: str
    filing: str
    facts: list[Fact] = field(default_factory=list)
