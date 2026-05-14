"""
test_defs_extractor.py — Smoke tests for definition extraction.

defs is the least-used linkbase; we verify it parses and surfaces
arcrole local names correctly.
"""

from pathlib import Path

import pytest

from xbrl_extraction import extract

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def apple_defs():
    matches = list(FIXTURES.glob("*1860*.zip"))
    if not matches:
        pytest.skip("Apple sample zip not present in tests/fixtures/")
    return extract(matches[0]).definitions


def test_defs_loaded(apple_defs):
    assert apple_defs is not None
    assert len(apple_defs.arcs) > 50


def test_defs_arcroles_are_local_names(apple_defs):
    # All arcroles should be local names, not long URIs
    arcroles = {a.arc_role for a in apple_defs.arcs}
    expected_subset = {
        "all",
        "hypercube-dimension",
        "dimension-domain",
        "dimension-default",
        "domain-member",
    }
    # At least some of these must appear
    assert arcroles & expected_subset
    # And none should look URL-shaped
    assert not any("/" in r for r in arcroles)
