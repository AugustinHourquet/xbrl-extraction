"""xbrl-extraction — transform iXBRL zip filings into structured JSON."""

# Silence bs4's XML-as-HTML warning at package import time. The iXBRL
# document is HTML with embedded XML namespaces — bs4's html parser
# handles it correctly, but the warning fires on every parse.
import warnings as _warnings

from bs4 import XMLParsedAsHTMLWarning as _XMLParsedAsHTMLWarning

_warnings.filterwarnings("ignore", category=_XMLParsedAsHTMLWarning)

# Public surface — re-export the stable types and entry points so users
# can `from xbrl_extraction import …` without caring about internal paths.
# Importing handlers binds operational methods onto Document
# (filter, to_dataframe, tree, verify, render_statement, summary, …).
# Done after Document is imported so the bind targets exist.
from xbrl_extraction import handlers as _handlers  # noqa: F401, E402
from xbrl_extraction.extractor import ExtractionResult, extract  # noqa: E402
from xbrl_extraction.linkbases import (  # noqa: E402
    CalcArc,
    Calculations,
    DefArc,
    Definitions,
    LabelEntry,
    Labels,
    PresArc,
    Presentation,
)
from xbrl_extraction.parsers.ixbrl import parse_ixbrl  # noqa: E402
from xbrl_extraction.schema import (  # noqa: E402
    Document,
    Fact,
    Filing,
    Period,
    Unit,
)

__version__ = "2.1.0"

__all__ = [
    # Entry points
    "extract",
    "ExtractionResult",
    "parse_ixbrl",
    # Schema
    "Document",
    "Fact",
    "Period",
    "Unit",
    "Filing",
    # Linkbase containers
    "Calculations",
    "CalcArc",
    "Presentation",
    "PresArc",
    "Labels",
    "LabelEntry",
    "Definitions",
    "DefArc",
]
