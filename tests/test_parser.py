"""
test_parser.py — Unit tests for the low-level parser.

Focused on the cases that bit us in v0 of the original codebase:
parentheses-negatives, scale/decimals attrs, dimensioned contexts,
and the divide unit shape.
"""

import pytest

from xbrl_extraction.parser import parse_ixbrl
from xbrl_extraction.utils import clean_numeric

# ---------------------------------------------------------------------------
# clean_numeric
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1,234", 1234.0),
        ("(1,234)", -1234.0),
        ("1,234.56", 1234.56),
        ("0", 0.0),
        ("  42 ", 42.0),
        ("1\xa0234", 1234.0),  # NBSP thousand sep
        ("", None),
        ("abc", None),
        ("(  )", None),
        (None, None),
    ],
)
def test_clean_numeric(raw, expected):
    assert clean_numeric(raw) == expected


# ---------------------------------------------------------------------------
# parse_ixbrl — minimal synthetic document
# ---------------------------------------------------------------------------

_MINIMAL_IXBRL = """
<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025">
<head><title>Test</title></head>
<body>
  <xbrli:context id="c-1">
    <xbrli:period>
      <xbrli:startDate>2024-01-01</xbrli:startDate>
      <xbrli:endDate>2024-12-31</xbrli:endDate>
    </xbrli:period>
  </xbrli:context>
  <xbrli:context id="c-2">
    <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <xbrli:context id="c-3">
    <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
    <xbrli:segment>
      <xbrldi:explicitMember xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
                             dimension="srt:ProductOrServiceAxis">us-gaap:ProductMember</xbrldi:explicitMember>
    </xbrli:segment>
  </xbrli:context>

  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <xbrli:unit id="usdPerShare">
    <xbrli:divide>
      <xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator>
      <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator>
    </xbrli:divide>
  </xbrli:unit>

  <p>
    Revenue:
    <ix:nonFraction name="us-gaap:Revenues" contextRef="c-1" unitRef="usd"
                    decimals="-6" scale="6">307,003</ix:nonFraction>
  </p>
  <p>
    Assets:
    <ix:nonFraction name="us-gaap:Assets" contextRef="c-2" unitRef="usd"
                    decimals="-6">364,980</ix:nonFraction>
  </p>
  <p>
    Product revenue (negative paren):
    <ix:nonFraction name="us-gaap:Revenues" contextRef="c-3" unitRef="usd"
                    decimals="-6">(1,500)</ix:nonFraction>
  </p>
  <p>
    EPS:
    <ix:nonFraction name="us-gaap:EarningsPerShareBasic" contextRef="c-1"
                    unitRef="usdPerShare" decimals="2">6.08</ix:nonFraction>
  </p>
</body></html>
"""


@pytest.fixture(scope="module")
def parsed():
    return parse_ixbrl(_MINIMAL_IXBRL)


def test_parses_all_facts(parsed):
    assert len(parsed.facts) == 4


def test_context_types(parsed):
    assert parsed.contexts["c-1"].type == "duration"
    assert parsed.contexts["c-1"].start_date == "2024-01-01"
    assert parsed.contexts["c-1"].end_date == "2024-12-31"
    assert parsed.contexts["c-2"].type == "instant"
    assert parsed.contexts["c-2"].date == "2024-12-31"


def test_dimensioned_context(parsed):
    dims = parsed.contexts["c-3"].dimensions
    assert dims == {"srt:ProductOrServiceAxis": "us-gaap:ProductMember"}


def test_simple_unit(parsed):
    assert parsed.units["usd"].measure == "iso4217:USD"
    assert parsed.units["usd"].numerator is None


def test_divide_unit(parsed):
    u = parsed.units["usdPerShare"]
    assert u.numerator == "iso4217:USD"
    assert u.denominator == "xbrli:shares"
    assert u.measure is None


def test_value_with_scale(parsed):
    # Value is preserved as filed — NOT multiplied by 10^6
    revenue = next(
        f for f in parsed.facts if f.concept == "us-gaap:Revenues" and f.context_ref == "c-1"
    )
    assert revenue.value == 307003
    assert revenue.scale == "6"
    assert revenue.decimals == "-6"


def test_paren_negative(parsed):
    neg = next(f for f in parsed.facts if f.context_ref == "c-3")
    assert neg.value == -1500
