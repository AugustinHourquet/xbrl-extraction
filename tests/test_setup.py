"""
test_setup.py — Verify the package scaffold is intact and importable.

Run with: pytest tests/test_setup.py -v
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = PROJECT_ROOT / "src" / "xbrl_extraction"


def test_required_dirs_exist():
    for sub in (
        "src/xbrl_extraction",
        "src/xbrl_extraction/parsers",
        "data/input",
        "data/output",
        "logs",
        "tests",
    ):
        assert (PROJECT_ROOT / sub).is_dir(), f"missing: {sub}"


def test_top_level_modules_exist():
    for module in (
        "__init__.py",
        "cli.py",
        "__main__.py",
        "extractor.py",
        "schema.py",
        "linkbases.py",
        "logger.py",
        "utils.py",
        "handlers.py",
    ):
        assert (PKG_ROOT / module).is_file(), f"missing: {module}"


def test_parsers_subpackage_modules_exist():
    for module in (
        "__init__.py",
        "ixbrl.py",
        "linkbase.py",
        "calc.py",
        "pres.py",
        "labs.py",
        "defs.py",
    ):
        assert (PKG_ROOT / "parsers" / module).is_file(), f"missing: parsers/{module}"


def test_public_imports():
    """The top-level package surface advertised in __init__ resolves."""
    from xbrl_extraction import (  # noqa: F401
        Calculations,
        Definitions,
        Document,
        Fact,
        Filing,
        Labels,
        Period,
        Presentation,
        Unit,
        extract,
        parse_ixbrl,
    )


def test_v1_parser_path_is_gone():
    """v2 hard-break: xbrl_extraction.parser no longer exists."""
    import importlib

    try:
        importlib.import_module("xbrl_extraction.parser")
    except ModuleNotFoundError:
        return
    raise AssertionError("xbrl_extraction.parser should be removed in v2")
