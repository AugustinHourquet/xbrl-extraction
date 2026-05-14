# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com),
and this project adheres to [Semantic Versioning](https://semver.org).

---

## [2.1.0] — 2026-05

### Added
- `scripts/inspect_filings.py` — standalone CLI inspector with four
  subcommands: `summary`, `statements`, `render`, `verify`. Resolves
  filings by company ID (the numeric segment of the source zip
  filename, e.g. `1860` for Apple).
- New Make targets wrapping the most common workflows:
  - **Extraction:** `extract FILE=...`, `extract-all`, `extract-force`,
    `extract-facts` (single file or batch).
  - **Inspection:** `summary`, `statements`, `render`, `verify` —
    each takes `FILE=<company_id>` with optional `YEAR=`, `ROLE=`,
    `DATE=`, `TOLERANCE=` qualifiers.
  - **Logs & cleanup:** `clean-output`, `log-tail`, `log-failures`.
  - **`make help`** lists everything with usage examples.
- `--facts-only` flag on the CLI: emit only `.facts.json` and skip
  the four linkbase JSONs. Idempotency in this mode checks against
  `.facts.json` alone.

### Changed
- `make format` and `make lint` now also cover `scripts/`.

---

## [2.0.0] — 2026-05

### Added
- Four new output files per filing alongside `.facts.json`:
  - **`.calc.json`** — calculation linkbase (arithmetic relationships:
    parent = Σ weight × child).
  - **`.pres.json`** — presentation linkbase (statement structure and
    display order).
  - **`.labs.json`** — label linkbase (human-readable concept names).
  - **`.defs.json`** — definition linkbase (dimensional constraints).
- `parsers/` subpackage grouping all format-specific parsers, with a
  shared `linkbase.py` for the XLink dialect used by all four
  linkbases.
- Role definitions extracted from the filing's `.xsd` and attached to
  `calc.json` and `pres.json`.
- Populated `handlers.py` — `Document` becomes a full consumption
  surface:
  - `Document.load()`, `Document.load_all()`, `from_dict()`,
    `to_dict()` round-trip.
  - `attach_calc()` / `attach_pres()` / `attach_labs()` /
    `attach_defs()` for explicit attachment; `load_all()` auto-discovers
    siblings.
  - `filter(**kwargs)` — chainable, returns a new pruned `Document`.
    Supports concept, period, unit, dimension, statement, and
    accounting-standard filters.
  - `to_dataframe()` — long-format pandas export.
  - Calc-aware navigation: `tree()`, `children_of()`, `parent_of()`,
    `expand()`, `verify()`.
  - `render_statement()` — single-period terminal-readable statement
    with `+`/`-` weight markers and accounting parentheses.
  - `summary()` — one-page filing overview.
- `ExtractionResult` dataclass returned by `extract()`, carrying the
  `Document` plus the four optional linkbase containers.
- `CHANGELOG.md` (this file).
- Top-level package re-exports the stable public surface (`extract`,
  `parse_ixbrl`, `Document`, `Calculations`, etc.) so users can
  `from xbrl_extraction import …` without touching internal paths.

### Changed
- `extract()` return type: was `Document`, now `ExtractionResult`. The
  document is at `result.document`; linkbases at `result.calc`,
  `result.presentation`, `result.labels`, `result.definitions`
  (any of which may be `None` if the corresponding linkbase file was
  missing or unparseable).
- Run log shape:
  - `output_file` (singular) → `output_files` (list).
  - Added per-linkbase counts: `calc_edges`, `pres_edges`,
    `labs_count`, `defs_edges`.
- Idempotency check now requires **all five** output files to exist
  before skipping. Any missing → regenerate all five (ensures
  consistent state).
- Linkbase failures degrade gracefully: a malformed `_cal.xml` logs a
  warning, leaves `result.calc = None`, and doesn't fail the
  extraction. The facts.json is always produced.
- `pandas` moved from dev to runtime dependency (required by handlers).

### Breaking
- **Removed** `xbrl_extraction.parser`. The module moved to
  `xbrl_extraction.parsers.ixbrl`. Use the top-level re-export
  (`from xbrl_extraction import parse_ixbrl`) to insulate against
  future moves.
- Run log shape change as listed under **Changed**. Consumers parsing
  prior `run_log.jsonl` files must look for `output_files` (plural)
  going forward.
- `extract()` return type change. Migration is mechanical: replace
  `doc = extract(...)` with `doc = extract(...).document`.

---

## [1.0.0] — 2026-05

### Added
- Initial release. iXBRL filing zip → structured JSON
  (`.facts.json` per filing).
- Faithful structural transcription: facts preserve concept, value,
  context, unit, scale, decimals, and dimensions exactly as filed.
- Auto-detection of accounting standard (US-GAAP / IFRS) from concept
  namespaces.
- Filing metadata (form, fiscal year, fiscal period, period end)
  lifted from `dei:` facts.
- Three-tier primary-document detection: `FilingSummary.xml` →
  `xmlns:ix=` namespace sniff → largest `.htm` fallback.
- Idempotent CLI: skip when output exists, `--force` to re-extract.
- Structured `logs/run_log.jsonl` (one line per filing processed).
- Empty `handlers.py` placeholder for v2.
