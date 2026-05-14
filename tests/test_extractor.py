"""
test_extractor.py — End-to-end tests against the sample filing zips.

These run only when sample zips are present in tests/fixtures/. The CI
flow drops them into that folder; locally, copy your input zips there
to enable.
"""

from pathlib import Path

import pytest

from xbrl_extraction import extract

FIXTURES = Path(__file__).parent / "fixtures"


def _find_zip(pattern: str) -> Path | None:
    matches = list(FIXTURES.glob(pattern))
    return matches[0] if matches else None


@pytest.fixture(scope="module")
def apple_doc():
    path = _find_zip("*1860*.zip")
    if path is None:
        pytest.skip("Apple sample zip not present in tests/fixtures/")
    return extract(path)


@pytest.fixture(scope="module")
def andersons_doc():
    path = _find_zip("*13091*.zip")
    if path is None:
        pytest.skip("Andersons sample zip not present in tests/fixtures/")
    return extract(path)


# ---------------------------------------------------------------------------
# Apple FY2025
# ---------------------------------------------------------------------------


def test_apple_filing_metadata(apple_doc):
    f = apple_doc.filing
    assert f.form == "10-K"
    assert f.fiscal_year == 2025
    assert f.fiscal_period == "FY"
    assert f.period_end == "2025-09-27"
    assert f.accounting_standard == "US-GAAP"
    assert f.primary_document.endswith(".htm")


def test_apple_has_many_facts(apple_doc):
    # Sanity floor — the FY2025 10-K has ~969 numeric facts
    assert len(apple_doc.facts) > 500


def test_apple_has_dimensioned_facts(apple_doc):
    dimensioned = [f for f in apple_doc.facts if f.dimensions]
    assert len(dimensioned) > 0


def test_apple_units(apple_doc):
    assert "usd" in apple_doc.units
    assert apple_doc.units["usd"].measure == "iso4217:USD"


# ---------------------------------------------------------------------------
# Andersons FY2025 (Dec year-end)
# ---------------------------------------------------------------------------


def test_andersons_filing_metadata(andersons_doc):
    f = andersons_doc.filing
    assert f.form == "10-K"
    assert f.fiscal_year == 2025
    assert f.period_end == "2025-12-31"
    assert f.accounting_standard == "US-GAAP"


def test_andersons_has_many_facts(andersons_doc):
    assert len(andersons_doc.facts) > 500


# ---------------------------------------------------------------------------
# Round-trip the dict shape
# ---------------------------------------------------------------------------


def test_apple_to_dict_shape(apple_doc):
    d = apple_doc.to_dict()
    assert set(d.keys()) == {"filing", "periods", "units", "facts"}
    assert isinstance(d["facts"], list)
    sample = d["facts"][0]
    assert set(sample.keys()) >= {"concept", "value", "unit", "period"}
