"""
test_handlers.py — Tests for the consumption layer.

Covers loading, attachment, filtering, dataframe export, calc-aware
methods, statement reconstruction, and summary.
"""

import json
from pathlib import Path

import pytest

from xbrl_extraction import Document, extract

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixtures: extract once, save to a tmp dir, then load from there
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def apple_output(tmp_path_factory):
    matches = list(FIXTURES.glob("*1860*.zip"))
    if not matches:
        pytest.skip("Apple sample zip not present in tests/fixtures/")

    out = tmp_path_factory.mktemp("apple_out")
    result = extract(matches[0])

    combined = {"facts": result.document.to_dict()}
    if result.calc:
        combined["calc"] = result.calc.to_dict()
    if result.presentation:
        combined["pres"] = result.presentation.to_dict()
    if result.labels:
        combined["labs"] = result.labels.to_dict()
    if result.definitions:
        combined["defs"] = result.definitions.to_dict()

    filing_path = out / "aapl.json"
    filing_path.write_text(json.dumps(combined))
    return filing_path


@pytest.fixture
def apple_full(apple_output):
    """Document with all four linkbases attached."""
    return Document.load(apple_output)


@pytest.fixture
def apple_facts_only(apple_output):
    """Document with only facts loaded."""
    return Document.load(apple_output, linkbases=False)


# ---------------------------------------------------------------------------
# Loading + round-trip
# ---------------------------------------------------------------------------


def test_load_facts_only(apple_facts_only):
    assert len(apple_facts_only.facts) > 500
    assert apple_facts_only.calc is None
    assert apple_facts_only.pres is None
    assert apple_facts_only.labs is None
    assert apple_facts_only.defs is None


def test_roundtrip(apple_output):
    """to_dict() of a loaded doc equals the source JSON's facts section."""
    original = json.loads(Path(apple_output).read_text())["facts"]
    doc = Document.load(apple_output, linkbases=False)
    revived = doc.to_dict()
    assert revived["filing"] == original["filing"]
    assert len(revived["facts"]) == len(original["facts"])
    assert revived["periods"] == original["periods"]
    assert revived["units"] == original["units"]


def test_load_attaches_linkbases(apple_full):
    assert apple_full.calc is not None
    assert apple_full.pres is not None
    assert apple_full.labs is not None
    assert apple_full.defs is not None


# ---------------------------------------------------------------------------
# Attach errors when calling linkbase-dependent methods
# ---------------------------------------------------------------------------


def test_verify_without_calc_raises(apple_facts_only):
    with pytest.raises(RuntimeError, match="not attached"):
        apple_facts_only.verify(period_end="2025-09-27")


def test_statement_filter_without_pres_raises(apple_facts_only):
    with pytest.raises(RuntimeError, match="not attached"):
        apple_facts_only.filter(statement="CONSOLIDATEDBALANCESHEETS")


def test_render_statement_without_pres_raises(apple_facts_only):
    with pytest.raises(RuntimeError, match="not attached"):
        apple_facts_only.render_statement(
            role_short="CONSOLIDATEDBALANCESHEETS", period_end="2025-09-27"
        )


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def test_filter_concept_exact(apple_full):
    sub = apple_full.filter(concept="us-gaap:Assets")
    assert len(sub.facts) > 0
    assert all(f.concept == "us-gaap:Assets" for f in sub.facts)


def test_filter_concept_contains(apple_full):
    sub = apple_full.filter(concept_contains="Revenue")
    assert len(sub.facts) > 0
    assert all("revenue" in f.concept.lower() for f in sub.facts)


def test_filter_unknown_kwarg_raises(apple_full):
    with pytest.raises(TypeError, match="unexpected keyword"):
        apple_full.filter(banana=True)


def test_filter_chainable(apple_full):
    sub = apple_full.filter(concept_contains="Revenue").filter(no_dimensions=True)
    assert all(not f.dimensions for f in sub.facts)


def test_filter_no_dimensions(apple_full):
    sub = apple_full.filter(no_dimensions=True)
    assert all(not f.dimensions for f in sub.facts)
    assert len(sub.facts) < len(apple_full.facts)


def test_filter_has_axis(apple_full):
    sub = apple_full.filter(has_axis="srt:ProductOrServiceAxis")
    assert len(sub.facts) > 0
    assert all("srt:ProductOrServiceAxis" in f.dimensions for f in sub.facts)


def test_filter_period_type(apple_full):
    sub = apple_full.filter(period_type="instant")
    assert all(apple_full.periods[f.period].type == "instant" for f in sub.facts)


def test_filter_period_end(apple_full):
    sub = apple_full.filter(period_end="2025-09-27")
    assert len(sub.facts) > 0


def test_filter_currency(apple_full):
    sub = apple_full.filter(currency=True)
    assert len(sub.facts) > 0
    for f in sub.facts:
        u = sub.units[f.unit]
        assert (u.measure or "").startswith("iso4217:")


def test_filter_statement(apple_full):
    sub = apple_full.filter(statement="CONSOLIDATEDBALANCESHEETS")
    assert len(sub.facts) > 0


def test_filter_returns_new_doc_with_pruned_dicts(apple_full):
    """Periods/units in the filtered doc are pruned to what's referenced."""
    sub = apple_full.filter(concept="us-gaap:Assets")
    used_periods = {f.period for f in sub.facts}
    used_units = {f.unit for f in sub.facts}
    assert set(sub.periods) == used_periods
    assert set(sub.units) == used_units


# ---------------------------------------------------------------------------
# DataFrame export
# ---------------------------------------------------------------------------


def test_to_dataframe_shape(apple_full):
    df = apple_full.to_dataframe()
    assert len(df) == len(apple_full.facts)
    expected_cols = {
        "concept",
        "value",
        "unit",
        "unit_measure",
        "period",
        "period_type",
        "period_start",
        "period_end",
        "period_date",
        "scale",
        "decimals",
        "dimensions",
        "source_file",
    }
    assert expected_cols.issubset(df.columns)


def test_to_dataframe_label_column_when_labs_attached(apple_full):
    df = apple_full.to_dataframe()
    assert "label" in df.columns


def test_to_dataframe_no_label_without_labs(apple_facts_only):
    df = apple_facts_only.to_dataframe()
    assert "label" not in df.columns


# ---------------------------------------------------------------------------
# Calc-aware methods
# ---------------------------------------------------------------------------


def test_children_of_assets(apple_full):
    children = apple_full.children_of("us-gaap:Assets", role_short="CONSOLIDATEDBALANCESHEETS")
    concepts = {c["concept"] for c in children}
    assert "us-gaap:AssetsCurrent" in concepts
    assert "us-gaap:AssetsNoncurrent" in concepts


def test_parent_of_assets_current(apple_full):
    parents = apple_full.parent_of("us-gaap:AssetsCurrent", role_short="CONSOLIDATEDBALANCESHEETS")
    assert any(p["concept"] == "us-gaap:Assets" for p in parents)


def test_tree_balance_sheet(apple_full):
    tree = apple_full.tree("CONSOLIDATEDBALANCESHEETS")
    # Tree has at least one root
    assert len(tree) >= 1
    # us-gaap:Assets is a node somewhere
    flat: set[str] = set()

    def walk(d):
        for k, v in d.items():
            flat.add(k)
            walk(v)

    walk(tree)
    assert "us-gaap:Assets" in flat


def test_expand_assets(apple_full):
    df = apple_full.expand(
        "us-gaap:Assets",
        role_short="CONSOLIDATEDBALANCESHEETS",
        period_end="2025-09-27",
    )
    assert "us-gaap:Assets" in df["concept"].values
    assert df["depth"].iloc[0] == 0  # root
    assert (df["depth"] > 0).any()  # descendants present


# ---------------------------------------------------------------------------
# verify() — the crown jewel
# ---------------------------------------------------------------------------


def test_verify_strict_balance_sheet(apple_full):
    df = apple_full.verify(
        role_short="CONSOLIDATEDBALANCESHEETS",
        period_end="2025-09-27",
        tolerance=0.0,
    )
    # Real BS for Apple should mostly match exactly
    statuses = df["status"].value_counts()
    assert statuses.get("match", 0) >= 5
    assert statuses.get("mismatch", 0) == 0  # no actual mismatches


def test_verify_strict_default(apple_full):
    """Default tolerance is 0.0."""
    df = apple_full.verify(
        role_short="CONSOLIDATEDBALANCESHEETS",
        period_end="2025-09-27",
    )
    assert df["status"].value_counts().get("match", 0) >= 5


def test_verify_returns_dataframe_with_expected_columns(apple_full):
    df = apple_full.verify(role_short="CONSOLIDATEDBALANCESHEETS", period_end="2025-09-27")
    assert set(df.columns) >= {"parent", "expected", "actual", "diff", "status", "role"}


# ---------------------------------------------------------------------------
# render_statement()
# ---------------------------------------------------------------------------


def test_render_statement_returns_string(apple_full):
    out = apple_full.render_statement(
        role_short="CONSOLIDATEDBALANCESHEETS",
        period_end="2025-09-27",
    )
    assert isinstance(out, str)
    assert "CONSOLIDATED BALANCE SHEETS" in out.upper()
    assert "Total assets" in out or "Assets" in out


def test_render_statement_unknown_role_raises(apple_full):
    with pytest.raises(ValueError, match="no presentation arcs"):
        apple_full.render_statement(role_short="NOT_A_REAL_ROLE", period_end="2025-09-27")


def test_render_statement_has_sign_prefixes(apple_full):
    out = apple_full.render_statement(
        role_short="CONSOLIDATEDBALANCESHEETS",
        period_end="2025-09-27",
    )
    # At least some leaves should be prefixed with `+ ` or `- `
    assert "+ " in out


# ---------------------------------------------------------------------------
# summary()
# ---------------------------------------------------------------------------


def test_summary_contains_filing_metadata(apple_full):
    s = apple_full.summary()
    assert "10-K" in s
    assert "2025" in s
    assert "US-GAAP" in s
    assert "Facts:" in s
    # All four linkbases attached → all show ✓
    assert "✓ calc" in s
    assert "✓ pres" in s
    assert "✓ labs" in s
    assert "✓ defs" in s


def test_summary_no_attachments(apple_facts_only):
    s = apple_facts_only.summary()
    assert "✗ calc" in s
    assert "✗ pres" in s
