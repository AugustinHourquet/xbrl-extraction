# tests/test_setup.py
import importlib
import pytest
from config.paths import ROOT, DATA, INPUT, OUTPUT, TAXONOMIES, DEBUG, LOGS


def test_root_exists():
    assert ROOT.exists() and ROOT.is_dir()


def test_data_dirs_exist():
    for path in [DATA, INPUT, OUTPUT, TAXONOMIES, DEBUG, LOGS]:
        assert path.exists() and path.is_dir(), f"Missing: {path}"


def test_paths_are_absolute():
    for path in [INPUT, OUTPUT, TAXONOMIES, DEBUG, LOGS]:
        assert path.is_absolute(), f"Not absolute: {path}"


def test_paths_are_inside_root():
    for path in [INPUT, OUTPUT, TAXONOMIES, DEBUG, LOGS]:
        assert str(path).startswith(str(ROOT)), f"Escapes ROOT: {path}"


@pytest.mark.parametrize(
    "module",
    [
        "xbrl_extraction",
        "xbrl_extraction.taxonomy",
        "xbrl_extraction.extractor",
        "xbrl_extraction.validator",
        "xbrl_extraction.schema",
        "xbrl_extraction.cli",
    ],
)
def test_module_importable(module):
    importlib.import_module(module)
