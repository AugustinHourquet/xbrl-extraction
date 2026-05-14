"""
parsers/defs.py — Definition linkbase extractor.

Reads a `_def.xml` file and produces a `Definitions` container that
serialises to `<basename>.defs.json`. Each arc represents a dimensional
relationship between concepts (which axes apply to which line items,
which members belong to which domains, etc.).
"""

from __future__ import annotations

import logging

from xbrl_extraction.linkbases import DefArc, Definitions
from xbrl_extraction.parsers.linkbase import (
    parse_linkbase,
    role_short,
)

logger = logging.getLogger(__name__)


def extract_definitions(def_xml: str, filing_meta: dict) -> Definitions:
    """
    Parse a definition linkbase XML and return a `Definitions`
    container ready to serialise.

    We pass through every arc regardless of arcrole — consumers filter
    by `arc_role` themselves. Common arcroles include `all`,
    `hypercube-dimension`, `dimension-domain`, `dimension-default`,
    `domain-member`.
    """
    linkbase = parse_linkbase(def_xml)

    arcs: list[DefArc] = []
    for arc in linkbase.arcs:
        arcs.append(
            DefArc(
                role=arc.role,
                role_short=role_short(arc.role),
                arc_role=arc.arc_role,
                from_=arc.from_,
                to=arc.to,
                order=arc.order,
            )
        )

    logger.info("Defs: %d arcs across %d roles", len(arcs), len({a.role for a in arcs}))

    return Definitions(filing=filing_meta, arcs=arcs)
