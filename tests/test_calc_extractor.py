"""
test_calc_extractor.py — End-to-end tests for calc extraction.

Runs against the sample filing zips in tests/fixtures/. Skips when
absent.
"""

from pathlib import Path

import pytest

from xbrl_extraction import extract

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def apple_calc():
    matches = list(FIXTURES.glob("*1860*.zip"))
    if not matches:
        pytest.skip("Apple sample zip not present in tests/fixtures/")
    return extract(matches[0]).calc


def test_calc_loaded(apple_calc):
    assert apple_calc is not None
    assert len(apple_calc.arcs) > 100  # AAPL has 213


def test_calc_role_definitions_resolved(apple_calc):
    # The balance-sheet role should be present and named
    assert any(v == "CONSOLIDATED BALANCE SHEETS" for v in apple_calc.role_definitions.values())


def test_calc_assets_has_known_children(apple_calc):
    """The fundamental BS identity: Assets = AssetsCurrent + AssetsNoncurrent."""
    bs_arcs = [
        a
        for a in apple_calc.arcs
        if a.role_short == "CONSOLIDATEDBALANCESHEETS" and a.parent == "us-gaap:Assets"
    ]
    children = {a.child for a in bs_arcs}
    assert "us-gaap:AssetsCurrent" in children
    assert "us-gaap:AssetsNoncurrent" in children
    assert all(a.weight == 1.0 for a in bs_arcs)


def test_calc_weights_are_real_numbers(apple_calc):
    for a in apple_calc.arcs:
        assert a.weight is not None
        assert isinstance(a.weight, float)
        # Real filings overwhelmingly use ±1 but we don't assume only ±1.
        assert a.weight != 0


def test_calc_roundtrip(apple_calc):
    """Calculations.to_dict() should round-trip via from_dict."""
    from xbrl_extraction.linkbases import Calculations

    d = apple_calc.to_dict()
    revived = Calculations.from_dict(d)
    assert len(revived.arcs) == len(apple_calc.arcs)
    assert revived.role_definitions == apple_calc.role_definitions
