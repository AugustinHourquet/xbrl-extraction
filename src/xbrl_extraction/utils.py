"""
utils.py — Low-level helpers shared by the parser and extractor.

Three things live here:
  1. `find_primary_document`: locate the main iXBRL .htm inside a zip
  2. `clean_numeric`:           normalise a raw iXBRL number string to float
  3. `read_htm`:                read + decode an htm file from a ZipFile

None of these depend on the schema or output shape; they could move to a
shared library without modification.
"""

from __future__ import annotations

import logging
import re
import zipfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Primary document detection
# ---------------------------------------------------------------------------

# Read just enough of each .htm to detect the iXBRL namespace declaration.
# 4KB is generous — the <html> tag with all its xmlns attrs sits in the
# first ~2KB of every SEC filing I've inspected.
_HEAD_SNIFF_BYTES = 4096
_IXBRL_NAMESPACE_MARKER = b"xmlns:ix="


def find_primary_document(zf: zipfile.ZipFile) -> str | None:
    """
    Identify the primary iXBRL document inside a filing zip.

    Strategy, in order:
      1. If `FilingSummary.xml` exists, parse it and use the report it
         flags as the primary instance. (SEC's own tooling does this.)
      2. Otherwise, scan all .htm files and pick the one whose head
         contains `xmlns:ix=` — the iXBRL namespace declaration. Exhibit
         documents (signatures, subsidiaries lists) don't carry it.
      3. As a last resort, fall back to the largest .htm and log a
         warning. Should never trigger on a well-formed SEC filing.
    """
    names = zf.namelist()

    # ── Strategy 1: FilingSummary.xml ───────────────────────────────────
    for name in names:
        if name.lower().endswith("filingsummary.xml"):
            primary = _parse_filing_summary(zf, name)
            if primary and primary in names:
                logger.debug("Primary doc via FilingSummary.xml: %s", primary)
                return primary
            break  # found summary but couldn't resolve — fall through

    htm_files = [n for n in names if n.lower().endswith(".htm")]
    if not htm_files:
        return None

    # ── Strategy 2: iXBRL namespace sniff ───────────────────────────────
    ixbrl_candidates = []
    for name in htm_files:
        try:
            head = zf.read(name)[:_HEAD_SNIFF_BYTES]
        except (KeyError, zipfile.BadZipFile):
            continue
        if _IXBRL_NAMESPACE_MARKER in head:
            ixbrl_candidates.append(name)

    if len(ixbrl_candidates) == 1:
        logger.debug("Primary doc via ix: namespace sniff: %s", ixbrl_candidates[0])
        return ixbrl_candidates[0]

    if len(ixbrl_candidates) > 1:
        # Pick the largest — the others are likely exhibits that happen to
        # share the namespace declaration. Very rare in practice.
        chosen = max(ixbrl_candidates, key=lambda n: zf.getinfo(n).file_size)
        logger.warning(
            "Multiple .htm files declare xmlns:ix= (%d candidates); " "picking largest: %s",
            len(ixbrl_candidates),
            chosen,
        )
        return chosen

    # ── Strategy 3: largest .htm fallback ───────────────────────────────
    chosen = max(htm_files, key=lambda n: zf.getinfo(n).file_size)
    logger.warning(
        "No .htm file declares xmlns:ix=; falling back to largest .htm: %s",
        chosen,
    )
    return chosen


def _parse_filing_summary(zf: zipfile.ZipFile, name: str) -> str | None:
    """Parse FilingSummary.xml and return the primary instance filename."""
    try:
        from xml.etree import ElementTree as ET

        root = ET.fromstring(zf.read(name))
    except (ET.ParseError, KeyError):
        return None

    # FilingSummary.xml structure: //Report/HtmlFileName, with the primary
    # instance flagged via <MenuCategory> or as the first report. The
    # schema isn't formally documented but SEC tooling treats the first
    # entry as primary in practice. We use heuristics instead.
    for report in root.iter("Report"):
        html_name = report.findtext("HtmlFileName")
        if html_name and "-" in html_name and html_name.lower().endswith(".htm"):
            # Primary docs follow <ticker>-<date>.htm; reports are R1.htm etc.
            if not re.match(r"^R\d+\.htm$", html_name, re.IGNORECASE):
                return html_name
    return None


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def read_htm(zf: zipfile.ZipFile, name: str) -> str:
    """Read a .htm file from a ZipFile and decode it to str."""
    raw = zf.read(name)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


# ---------------------------------------------------------------------------
# Number cleaning
# ---------------------------------------------------------------------------

# Strip HTML-entity remnants and zero-width characters that occasionally
# leak through from iXBRL nonFraction text content.
_ENTITY_RE = re.compile(r"&[a-zA-Z]+;")


def clean_numeric(raw: str) -> float | None:
    """
    Convert raw iXBRL nonFraction text to a float.

    Handles:
      - parentheses for negatives: "(1,234)"  → -1234.0
      - comma thousand separators: "1,234.56" → 1234.56
      - non-breaking & zero-width spaces (NBSP, ZWSP)
      - leftover HTML entities

    Does NOT apply `scale` or `decimals` — values are returned exactly as
    they appear in the source text (per the v1 design: preserve as filed).

    Returns None if the value can't be parsed.
    """
    if raw is None:
        return None

    text = raw.replace("\xa0", "").replace("\u200b", "").strip()
    text = _ENTITY_RE.sub("", text).strip()
    if not text:
        return None

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()

    text = text.replace(",", "").replace(" ", "")

    try:
        value = float(text)
    except ValueError:
        return None

    return -value if negative else value
