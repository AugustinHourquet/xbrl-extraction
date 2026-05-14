"""
parsers/linkbase.py — Generic XLink-based linkbase parser.

All four XBRL linkbases (_cal, _pre, _lab, _def) share the same XLink
dialect: extended links scoped by xlink:role, containing
  - <link:loc>  — local label → concept reference (via xlink:href fragment)
  - <link:*Arc> — relationships between two xlink:labels
  - <link:label> (labs only) — label resources bound by labelArc

This module exposes one entry point — `parse_linkbase()` — that returns
a `Linkbase` containing every arc, with locator labels already resolved
to concept names. The format-specific extractors (calc/pres/labs/defs)
shape that into their respective output JSON.

Role definitions live in the schema (.xsd), not the linkbase. Use
`parse_role_definitions()` to extract them.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# XML namespaces — the linkbase dialect uses two
# ---------------------------------------------------------------------------

_NS = {
    "link": "http://www.xbrl.org/2003/linkbase",
    "xlink": "http://www.w3.org/1999/xlink",
    "xml": "http://www.w3.org/XML/1998/namespace",
}


def _q(prefix: str, local: str) -> str:
    """Build the Clark notation for an XML element ({namespace}localname)."""
    return f"{{{_NS[prefix]}}}{local}"


# ---------------------------------------------------------------------------
# Data shape
# ---------------------------------------------------------------------------


@dataclass
class LinkbaseArc:
    """One resolved arc — concept-to-concept (or concept-to-label-resource)."""

    role: str
    arc_role: str  # local name only ("summation-item", etc.)
    from_: str  # concept name (or label-resource id for labelArc)
    to: str
    order: float = 0.0
    # Optional attrs surfaced for specific linkbases:
    weight: float | None = None  # calc
    preferred_label: str | None = None  # pres


@dataclass
class LabelResource:
    """A <link:label> element from a labs linkbase."""

    label_id: str  # xlink:label (matched against labelArc.to)
    role: str  # xlink:role — the label-role URI
    language: str  # xml:lang
    text: str


@dataclass
class Linkbase:
    """Output of parse_linkbase — all arcs across all roles."""

    arcs: list[LinkbaseArc] = field(default_factory=list)
    # Labels-only side channel; empty for calc/pres/defs.
    label_resources: list[LabelResource] = field(default_factory=list)
    # Per-arc unresolved label-resource references (labelArc only).
    # Used by parsers/labs.py to bind labels to concepts.
    arc_targets: list[tuple[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Concept resolution from xlink:href fragments
# ---------------------------------------------------------------------------

# An xlink:href looks like:
#   https://xbrl.fasb.org/us-gaap/2025/elts/us-gaap-2025.xsd#us-gaap_Assets
#   aapl-20250927.xsd#aapl_Revenues
# The concept is the URL fragment after #, with the underscore restored to colon.
_FRAGMENT_RE = re.compile(r"#(.+)$")


def _href_to_concept(href: str) -> str | None:
    """
    Convert an xlink:href URL into a concept name.

    `us-gaap_Assets` → `us-gaap:Assets`
    `aapl_Revenues`  → `aapl:Revenues`
    """
    m = _FRAGMENT_RE.search(href or "")
    if not m:
        return None
    frag = m.group(1)
    # Only the FIRST underscore separates prefix from local name; the
    # local name can legitimately contain underscores.
    if "_" not in frag:
        return frag
    prefix, local = frag.split("_", 1)
    return f"{prefix}:{local}"


# ---------------------------------------------------------------------------
# Arcrole / arc-element name normalisation
# ---------------------------------------------------------------------------


def arcrole_local_name(arcrole_uri: str) -> str:
    """
    Strip the long URL prefix from an arcrole URI, leaving only the
    local name. Tolerant of trailing fragments.

      "http://www.xbrl.org/2003/arcrole/summation-item" → "summation-item"
      "http://xbrl.org/int/dim/arcrole/hypercube-dimension" → "hypercube-dimension"
    """
    if not arcrole_uri:
        return ""
    return arcrole_uri.rsplit("/", 1)[-1]


def role_short(role_uri: str) -> str:
    """Last path segment of a role URI — e.g. CONSOLIDATEDBALANCESHEETS."""
    if not role_uri:
        return ""
    return role_uri.rsplit("/", 1)[-1]


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

# Arc element names we care about, keyed by linkbase type. Each linkbase
# uses one of these; we accept any since `parse_linkbase` is generic.
_ARC_ELEMENTS = {
    _q("link", "calculationArc"),
    _q("link", "presentationArc"),
    _q("link", "labelArc"),
    _q("link", "definitionArc"),
}

# Containing extended-link element names (the role-scoped wrappers).
_LINK_ELEMENTS = {
    _q("link", "calculationLink"),
    _q("link", "presentationLink"),
    _q("link", "labelLink"),
    _q("link", "definitionLink"),
}


def parse_linkbase(xml_content: str) -> Linkbase:
    """
    Parse a linkbase XML document into a flat list of resolved arcs.

    For each <link:*Link> in the document:
      1. Read xlink:role — the role this link scopes.
      2. Build a label→concept map from child <link:loc> elements.
      3. For each child <link:*Arc>:
           - resolve from / to through the label map
           - extract weight, preferred_label, order as applicable
           - append a LinkbaseArc to the output.
      4. For each child <link:label> resource (labs only):
           - append a LabelResource and remember the labelArc's
             unresolved (concept → label_id) target so the caller
             can bind them.

    Arcs whose endpoints can't be resolved are dropped with a debug log
    (typically resource-only labels that aren't concepts).
    """
    out = Linkbase()

    root = ET.fromstring(xml_content)
    for link in root:
        if link.tag not in _LINK_ELEMENTS:
            continue

        role = link.get(_q("xlink", "role"), "")

        # ── Build local label → concept map for this extended link ──
        label_to_concept: dict[str, str] = {}
        # And the inverse for labelArc binding (label-resource lookups):
        label_resources_here: dict[str, LabelResource] = {}

        for loc in link.findall(_q("link", "loc")):
            label = loc.get(_q("xlink", "label"))
            href = loc.get(_q("xlink", "href"))
            concept = _href_to_concept(href)
            if label and concept:
                label_to_concept[label] = concept

        # ── Collect label resources (labs only) ───────────────────────
        for lbl in link.findall(_q("link", "label")):
            res = LabelResource(
                label_id=lbl.get(_q("xlink", "label"), ""),
                role=lbl.get(_q("xlink", "role"), ""),
                language=lbl.get(_q("xml", "lang"), "en-US"),
                text=(lbl.text or "").strip(),
            )
            out.label_resources.append(res)
            label_resources_here.setdefault(res.label_id, res)

        # ── Walk arcs ────────────────────────────────────────────────
        for arc in link:
            if arc.tag not in _ARC_ELEMENTS:
                continue

            from_label = arc.get(_q("xlink", "from"))
            to_label = arc.get(_q("xlink", "to"))
            if not (from_label and to_label):
                continue

            from_concept = label_to_concept.get(from_label)
            to_concept = label_to_concept.get(to_label)

            arcrole = arcrole_local_name(arc.get(_q("xlink", "arcrole"), ""))
            order_raw = arc.get("order", "0")
            try:
                order = float(order_raw)
            except ValueError:
                order = 0.0

            # labelArc: `to` points to a label-resource, not a concept.
            # Surface as arc_targets so the labs extractor can resolve.
            if arc.tag == _q("link", "labelArc"):
                if from_concept and to_label in label_resources_here:
                    out.arc_targets.append((from_concept, to_label))
                continue

            if not (from_concept and to_concept):
                logger.debug(
                    "Dropping unresolvable %s arc in role %s",
                    arcrole,
                    role,
                )
                continue

            weight_raw = arc.get("weight")
            try:
                weight = float(weight_raw) if weight_raw is not None else None
            except ValueError:
                weight = None

            preferred = arc.get("preferredLabel")

            out.arcs.append(
                LinkbaseArc(
                    role=role,
                    arc_role=arcrole,
                    from_=from_concept,
                    to=to_concept,
                    order=order,
                    weight=weight,
                    preferred_label=preferred,
                )
            )

    return out


# ---------------------------------------------------------------------------
# Role definitions (live in the .xsd, not the linkbase)
# ---------------------------------------------------------------------------

# A roleType element looks like:
#   <link:roleType id="..." roleURI="...">
#     <link:definition>9952153 - Statement - CONSOLIDATED BALANCE SHEETS</link:definition>
#     <link:usedOn>...</link:usedOn>
#   </link:roleType>
#
# We split the definition on " - " and keep the trailing human name.

_DEF_SEPARATOR = re.compile(r"\s+-\s+")


def parse_role_definitions(xsd_content: str) -> dict[str, str]:
    """
    Extract {role_URI → human-readable name} from a filing's .xsd.

    For "9952153 - Statement - CONSOLIDATED BALANCE SHEETS", returns
    "CONSOLIDATED BALANCE SHEETS" (last segment after " - ").

    Returns an empty dict on parse failure rather than raising; role
    definitions are nice-to-have, not load-bearing.
    """
    try:
        root = ET.fromstring(xsd_content)
    except ET.ParseError as exc:
        logger.warning("Could not parse .xsd for role definitions: %s", exc)
        return {}

    result: dict[str, str] = {}
    for rt in root.iter(_q("link", "roleType")):
        role_uri = rt.get("roleURI")
        if not role_uri:
            continue
        defn = rt.find(_q("link", "definition"))
        if defn is None or not (defn.text or "").strip():
            continue
        parts = _DEF_SEPARATOR.split(defn.text.strip())
        result[role_uri] = parts[-1].strip() if parts else defn.text.strip()

    return result
