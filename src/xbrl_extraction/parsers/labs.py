"""
parsers/labs.py — Label linkbase extractor.

Reads a `_lab.xml` file and produces a `Labels` container that
serialises to `<basename>.labs.json`.

Labs is structurally different from calc/pres/defs:
  - <link:loc>      — concept reference (as in other linkbases)
  - <link:label>    — a label-resource with role, language, and text
  - <link:labelArc> — binds a concept to a label-resource

The shared parser collects all three pieces; this module joins them
into flat (concept, label_role, language, text) records.
"""

from __future__ import annotations

import logging

from xbrl_extraction.linkbases import LabelEntry, Labels
from xbrl_extraction.parsers.linkbase import parse_linkbase

logger = logging.getLogger(__name__)


def extract_labels(lab_xml: str, filing_meta: dict) -> Labels:
    """
    Parse a label linkbase XML and return a `Labels` container ready
    to serialise.

    The shared parser deposits:
      - label_resources: every <link:label> with role/language/text
      - arc_targets:     (concept, label_id) pairs from labelArc

    A single label_id may resolve to multiple resources (typically not,
    but the spec allows it). We emit one LabelEntry per (concept, role,
    language, text) tuple.
    """
    linkbase = parse_linkbase(lab_xml)

    # Index label resources by their xlink:label id.
    by_id: dict[str, list] = {}
    for res in linkbase.label_resources:
        by_id.setdefault(res.label_id, []).append(res)

    entries: list[LabelEntry] = []
    seen: set[tuple[str, str, str, str]] = set()

    for concept, label_id in linkbase.arc_targets:
        for res in by_id.get(label_id, []):
            key = (concept, res.role, res.language, res.text)
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                LabelEntry(
                    concept=concept,
                    label_role=res.role,
                    language=res.language,
                    text=res.text,
                )
            )

    logger.info(
        "Labs: %d label entries for %d concepts", len(entries), len({e.concept for e in entries})
    )

    return Labels(filing=filing_meta, entries=entries)
