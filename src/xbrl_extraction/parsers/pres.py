"""
parsers/pres.py — Presentation linkbase extractor.

Reads a `_pre.xml` file and produces a `Presentation` container that
serialises to `<basename>.pres.json`. Each arc represents a display
relationship: child appears under parent in a specific role (statement).
"""

from __future__ import annotations

import logging

from xbrl_extraction.linkbases import PresArc, Presentation
from xbrl_extraction.parsers.linkbase import (
    parse_linkbase,
    role_short,
)

logger = logging.getLogger(__name__)


# Presentation uses parent-child. We accept arcs without an arcrole,
# but the standard one is parent-child.
_PRES_ARCROLE = "parent-child"


def extract_presentation(
    pre_xml: str,
    filing_meta: dict,
    role_definitions: dict[str, str] | None = None,
) -> Presentation:
    """
    Parse a presentation linkbase XML and return a `Presentation`
    container ready to serialise.
    """
    linkbase = parse_linkbase(pre_xml)
    role_definitions = role_definitions or {}

    arcs: list[PresArc] = []
    for arc in linkbase.arcs:
        # Be lenient: accept parent-child or any arc, since some filers
        # omit the arcrole on presentation arcs.
        if arc.arc_role and arc.arc_role != _PRES_ARCROLE:
            continue
        arcs.append(
            PresArc(
                role=arc.role,
                role_short=role_short(arc.role),
                role_definition=role_definitions.get(arc.role, ""),
                parent=arc.from_,
                child=arc.to,
                order=arc.order,
                preferred_label=arc.preferred_label,
            )
        )

    logger.info("Pres: %d arcs across %d roles", len(arcs), len({a.role for a in arcs}))

    return Presentation(filing=filing_meta, arcs=arcs)
