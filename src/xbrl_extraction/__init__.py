"""xbrl-extraction — transform iXBRL zip filings into structured JSON."""

# Silence bs4's XML-as-HTML warning at package import time. The iXBRL
# document is HTML with embedded XML namespaces — bs4's html parser
# handles it correctly, but the warning fires on every parse. Applying
# the filter here covers both parser.py and extractor.py.
import warnings as _warnings

from bs4 import XMLParsedAsHTMLWarning as _XMLParsedAsHTMLWarning

from xbrl_extraction.extractor import extract
from xbrl_extraction.schema import Document, Fact, Filing, Period, Unit

_warnings.filterwarnings("ignore", category=_XMLParsedAsHTMLWarning)

__all__ = ["extract", "Document", "Fact", "Period", "Unit", "Filing"]
__version__ = "1.0.0"
