"""
test_pres_extractor.py — End-to-end tests for presentation extraction.
"""

from pathlib import Path

import pytest

from xbrl_extraction import extract

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def apple_pres():
    matches = list(FIXTURES.glob("*1860*.zip"))
    if not matches:
        pytest.skip("Apple sample zip not present in tests/fixtures/")
    return extract(matches[0]).presentation


def test_pres_loaded(apple_pres):
    assert apple_pres is not None
    assert len(apple_pres.arcs) > 500


def test_pres_has_balance_sheet_statement(apple_pres):
    bs = [a for a in apple_pres.arcs if a.role_short == "CONSOLIDATEDBALANCESHEETS"]
    assert len(bs) > 0
    # role_definition resolved from .xsd
    assert any("BALANCE SHEET" in (a.role_definition or "").upper() for a in bs)


def test_pres_preferred_label_carried(apple_pres):
    # Many but not all arcs carry a preferredLabel
    assert any(a.preferred_label for a in apple_pres.arcs)


def test_pres_orders_are_floats(apple_pres):
    for a in apple_pres.arcs[:50]:
        assert isinstance(a.order, float)
