"""
test_setup.py — Verify the package scaffold is intact and importable.

Run with: pytest tests/test_setup.py -v
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_required_dirs_exist():
    for sub in ("src/xbrl_extraction", "data/input", "data/output", "logs", "tests"):
        assert (PROJECT_ROOT / sub).is_dir(), f"missing: {sub}"


def test_required_modules_exist():
    for module in (
        "__init__.py",
        "cli.py",
        "__main__.py",
        "extractor.py",
        "parser.py",
        "schema.py",
        "logger.py",
        "utils.py",
        "handlers.py",
    ):
        assert (PROJECT_ROOT / "src" / "xbrl_extraction" / module).is_file(), f"missing: {module}"


def test_public_imports():
    """The package surface advertised in __init__ should resolve."""
    from xbrl_extraction import Document, Fact, Filing, Period, Unit, extract  # noqa: F401
