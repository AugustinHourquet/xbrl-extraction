"""
parsers/calc.py — Calculation linkbase extractor.

Reads a `_cal.xml` file and produces a `Calculations` container that
serialises to `<basename>.calc.json`. Each arc represents an arithmetic
relationship: parent = parent + (weight × child) in a given role.
"""

from __future__ import annotations

import logging

from xbrl_extraction.linkbases import CalcArc, Calculations
from xbrl_extraction.parsers.linkbase import (
    parse_linkbase,
    role_short,
)

logger = logging.getLogger(__name__)


# Only summation-item arcs carry arithmetic meaning. Filter aggressively
# so consumers don't have to.
_CALC_ARCROLE = "summation-item"


def extract_calculations(
    cal_xml: str,
    filing_meta: dict,
    role_definitions: dict[str, str] | None = None,
) -> Calculations:
    """
    Parse a calculation linkbase XML and return a `Calculations`
    container ready to serialise.

    Args:
        cal_xml:          raw bytes of `<basename>_cal.xml`, decoded.
        filing_meta:      the {source_file, primary_document} block.
        role_definitions: optional {role_URI: human_name} from the .xsd.
    """
    linkbase = parse_linkbase(cal_xml)
    role_definitions = role_definitions or {}

    arcs: list[CalcArc] = []
    for arc in linkbase.arcs:
        if arc.arc_role != _CALC_ARCROLE:
            continue
        if arc.weight is None:
            logger.debug(
                "Calc arc with no weight: %s → %s; skipping",
                arc.from_,
                arc.to,
            )
            continue
        arcs.append(
            CalcArc(
                role=arc.role,
                role_short=role_short(arc.role),
                parent=arc.from_,
                child=arc.to,
                weight=arc.weight,
                order=arc.order,
            )
        )

    logger.info("Calc: %d arcs across %d roles", len(arcs), len({a.role for a in arcs}))

    return Calculations(
        filing=filing_meta,
        role_definitions=role_definitions,
        arcs=arcs,
    )
