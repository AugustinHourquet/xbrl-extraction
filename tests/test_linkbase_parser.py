"""
test_linkbase_parser.py — Tests for the shared XLink parser.

Covers:
  - href → concept resolution (standard and filer namespaces)
  - arcrole local-name stripping
  - role_short URL slicing
  - Full parse of a synthetic linkbase with all four arc types
  - Role definition extraction from a synthetic .xsd
"""

from xbrl_extraction.parsers.linkbase import (
    _href_to_concept,
    arcrole_local_name,
    parse_linkbase,
    parse_role_definitions,
    role_short,
)

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_href_to_concept_standard_taxonomy():
    assert (
        _href_to_concept("https://xbrl.fasb.org/us-gaap/2025/elts/us-gaap-2025.xsd#us-gaap_Assets")
        == "us-gaap:Assets"
    )


def test_href_to_concept_filer_extension():
    assert _href_to_concept("aapl-20250927.xsd#aapl_Revenues") == "aapl:Revenues"


def test_href_to_concept_local_name_with_underscores():
    # Local name can contain underscores; only the FIRST split matters.
    assert (
        _href_to_concept("foo.xsd#us-gaap_SomeReallyLongName_WithUnderscores")
        == "us-gaap:SomeReallyLongName_WithUnderscores"
    )


def test_href_to_concept_missing_fragment():
    assert _href_to_concept("aapl.xsd") is None
    assert _href_to_concept("") is None


def test_arcrole_local_name():
    assert arcrole_local_name("http://www.xbrl.org/2003/arcrole/summation-item") == "summation-item"
    assert (
        arcrole_local_name("http://xbrl.org/int/dim/arcrole/hypercube-dimension")
        == "hypercube-dimension"
    )
    assert arcrole_local_name("") == ""


def test_role_short():
    assert (
        role_short("http://www.apple.com/role/CONSOLIDATEDBALANCESHEETS")
        == "CONSOLIDATEDBALANCESHEETS"
    )
    assert role_short("") == ""


# ---------------------------------------------------------------------------
# Synthetic linkbase parse — exercises all four arc types
# ---------------------------------------------------------------------------

_SYNTHETIC_CAL = """<?xml version="1.0" encoding="UTF-8"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:calculationLink xlink:role="http://test/role/BS" xlink:type="extended">
    <link:loc xlink:type="locator"
              xlink:label="loc_a"
              xlink:href="test.xsd#us-gaap_Assets"/>
    <link:loc xlink:type="locator"
              xlink:label="loc_b"
              xlink:href="test.xsd#us-gaap_AssetsCurrent"/>
    <link:loc xlink:type="locator"
              xlink:label="loc_c"
              xlink:href="test.xsd#us-gaap_AssetsNoncurrent"/>
    <link:calculationArc xlink:type="arc"
                         xlink:arcrole="http://www.xbrl.org/2003/arcrole/summation-item"
                         xlink:from="loc_a" xlink:to="loc_b"
                         order="1" weight="1.0"/>
    <link:calculationArc xlink:type="arc"
                         xlink:arcrole="http://www.xbrl.org/2003/arcrole/summation-item"
                         xlink:from="loc_a" xlink:to="loc_c"
                         order="2" weight="1.0"/>
  </link:calculationLink>
</link:linkbase>"""


def test_calc_synthetic_parses_two_arcs():
    lb = parse_linkbase(_SYNTHETIC_CAL)
    assert len(lb.arcs) == 2
    assert {a.to for a in lb.arcs} == {
        "us-gaap:AssetsCurrent",
        "us-gaap:AssetsNoncurrent",
    }
    assert all(a.from_ == "us-gaap:Assets" for a in lb.arcs)
    assert all(a.weight == 1.0 for a in lb.arcs)
    assert all(a.arc_role == "summation-item" for a in lb.arcs)
    assert all(a.role == "http://test/role/BS" for a in lb.arcs)


def test_calc_synthetic_preserves_order():
    lb = parse_linkbase(_SYNTHETIC_CAL)
    by_order = sorted(lb.arcs, key=lambda a: a.order)
    assert by_order[0].to == "us-gaap:AssetsCurrent"
    assert by_order[1].to == "us-gaap:AssetsNoncurrent"


# ---------------------------------------------------------------------------
# Synthetic presentation linkbase — preferredLabel surfaces
# ---------------------------------------------------------------------------

_SYNTHETIC_PRES = """<?xml version="1.0" encoding="UTF-8"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:presentationLink xlink:role="http://test/role/X" xlink:type="extended">
    <link:loc xlink:label="loc_p" xlink:href="t.xsd#x_Parent" xlink:type="locator"/>
    <link:loc xlink:label="loc_c" xlink:href="t.xsd#x_Child" xlink:type="locator"/>
    <link:presentationArc xlink:type="arc"
                          xlink:arcrole="http://www.xbrl.org/2003/arcrole/parent-child"
                          xlink:from="loc_p" xlink:to="loc_c"
                          order="1"
                          preferredLabel="http://www.xbrl.org/2003/role/terseLabel"/>
  </link:presentationLink>
</link:linkbase>"""


def test_pres_synthetic_carries_preferred_label():
    lb = parse_linkbase(_SYNTHETIC_PRES)
    assert len(lb.arcs) == 1
    assert lb.arcs[0].preferred_label == "http://www.xbrl.org/2003/role/terseLabel"


# ---------------------------------------------------------------------------
# Synthetic labs linkbase — label resources + labelArc binding
# ---------------------------------------------------------------------------

_SYNTHETIC_LABS = """<?xml version="1.0" encoding="UTF-8"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink"
               xmlns:xml="http://www.w3.org/XML/1998/namespace">
  <link:labelLink xlink:role="http://www.xbrl.org/2003/role/link" xlink:type="extended">
    <link:loc xlink:type="locator"
              xlink:label="loc_assets"
              xlink:href="t.xsd#us-gaap_Assets"/>
    <link:label xlink:type="resource"
                xlink:label="lab_assets_std"
                xlink:role="http://www.xbrl.org/2003/role/label"
                xml:lang="en-US">Assets</link:label>
    <link:label xlink:type="resource"
                xlink:label="lab_assets_total"
                xlink:role="http://www.xbrl.org/2003/role/totalLabel"
                xml:lang="en-US">Total assets</link:label>
    <link:labelArc xlink:type="arc"
                   xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label"
                   xlink:from="loc_assets" xlink:to="lab_assets_std"/>
    <link:labelArc xlink:type="arc"
                   xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label"
                   xlink:from="loc_assets" xlink:to="lab_assets_total"/>
  </link:labelLink>
</link:linkbase>"""


def test_labs_synthetic_collects_resources_and_targets():
    lb = parse_linkbase(_SYNTHETIC_LABS)
    # Two label resources, two arc_targets, zero "regular" arcs.
    assert len(lb.label_resources) == 2
    assert len(lb.arc_targets) == 2
    assert len(lb.arcs) == 0
    # Resources carry text/role/lang
    by_role = {r.role: r for r in lb.label_resources}
    assert by_role["http://www.xbrl.org/2003/role/label"].text == "Assets"
    assert by_role["http://www.xbrl.org/2003/role/totalLabel"].text == "Total assets"
    # Targets bind concept name to label-id
    concepts = {t[0] for t in lb.arc_targets}
    assert concepts == {"us-gaap:Assets"}


# ---------------------------------------------------------------------------
# Synthetic defs linkbase — arcrole local-name stripped
# ---------------------------------------------------------------------------

_SYNTHETIC_DEFS = """<?xml version="1.0" encoding="UTF-8"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:definitionLink xlink:role="http://test/role/Y" xlink:type="extended">
    <link:loc xlink:label="loc_t" xlink:href="t.xsd#us-gaap_Table" xlink:type="locator"/>
    <link:loc xlink:label="loc_a" xlink:href="t.xsd#srt_ProductOrServiceAxis" xlink:type="locator"/>
    <link:definitionArc xlink:type="arc"
                        xlink:arcrole="http://xbrl.org/int/dim/arcrole/hypercube-dimension"
                        xlink:from="loc_t" xlink:to="loc_a"
                        order="1"/>
  </link:definitionLink>
</link:linkbase>"""


def test_defs_synthetic_strips_arcrole_uri():
    lb = parse_linkbase(_SYNTHETIC_DEFS)
    assert len(lb.arcs) == 1
    assert lb.arcs[0].arc_role == "hypercube-dimension"


# ---------------------------------------------------------------------------
# Unresolvable arcs (missing locator) are dropped silently
# ---------------------------------------------------------------------------

_UNRESOLVABLE = """<?xml version="1.0" encoding="UTF-8"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:calculationLink xlink:role="http://test/role/X" xlink:type="extended">
    <link:calculationArc xlink:type="arc"
                         xlink:arcrole="http://www.xbrl.org/2003/arcrole/summation-item"
                         xlink:from="nonexistent_a" xlink:to="nonexistent_b"
                         weight="1.0"/>
  </link:calculationLink>
</link:linkbase>"""


def test_unresolvable_arc_is_dropped():
    lb = parse_linkbase(_UNRESOLVABLE)
    assert lb.arcs == []


# ---------------------------------------------------------------------------
# Role definitions from .xsd
# ---------------------------------------------------------------------------

_SYNTHETIC_XSD = """<?xml version="1.0" encoding="UTF-8"?>
<schema xmlns="http://www.w3.org/2001/XMLSchema"
        xmlns:link="http://www.xbrl.org/2003/linkbase">
  <annotation>
    <appinfo>
      <link:roleType id="BS" roleURI="http://test/role/BS">
        <link:definition>9952153 - Statement - CONSOLIDATED BALANCE SHEETS</link:definition>
        <link:usedOn>link:presentationLink</link:usedOn>
      </link:roleType>
      <link:roleType id="IS" roleURI="http://test/role/IS">
        <link:definition>9952154 - Statement - Income Statement</link:definition>
        <link:usedOn>link:presentationLink</link:usedOn>
      </link:roleType>
    </appinfo>
  </annotation>
</schema>"""


def test_role_definitions_extracted_from_xsd():
    rd = parse_role_definitions(_SYNTHETIC_XSD)
    assert rd == {
        "http://test/role/BS": "CONSOLIDATED BALANCE SHEETS",
        "http://test/role/IS": "Income Statement",
    }


def test_role_definitions_handles_malformed_xsd():
    # Bad XML returns {} instead of raising.
    assert parse_role_definitions("<not valid xml") == {}
