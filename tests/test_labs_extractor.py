"""
test_labs_extractor.py — End-to-end tests for label extraction.
"""

from pathlib import Path

import pytest

from xbrl_extraction import extract
from xbrl_extraction.linkbases import Labels

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def apple_labs():
    matches = list(FIXTURES.glob("*1860*.zip"))
    if not matches:
        pytest.skip("Apple sample zip not present in tests/fixtures/")
    return extract(matches[0]).labels


def test_labs_loaded(apple_labs):
    assert apple_labs is not None
    assert len(apple_labs.entries) > 100


def test_labs_resolves_assets_standard_label(apple_labs):
    text = apple_labs.get("us-gaap:Assets")
    # Either "Assets" (standardLabel) or whatever the filer chose
    assert text is not None
    assert len(text) > 0


def test_labs_total_label_variant(apple_labs):
    # If a totalLabel exists for Assets, it's distinct from the standard one
    has_total = any(
        e.concept == "us-gaap:Assets" and e.label_role == Labels.TOTAL for e in apple_labs.entries
    )
    if has_total:
        std = apple_labs.get("us-gaap:Assets", preferred_label=Labels.STANDARD)
        total = apple_labs.get("us-gaap:Assets", preferred_label=Labels.TOTAL)
        assert std is not None
        assert total is not None


def test_labs_unknown_concept_returns_none(apple_labs):
    assert apple_labs.get("definitely:NotAConcept") is None


def test_labs_roundtrip(apple_labs):
    revived = Labels.from_dict(apple_labs.to_dict())
    assert len(revived.entries) == len(apple_labs.entries)
