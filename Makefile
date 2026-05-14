# Make targets for xbrl-extraction.
#
# Convention: targets that operate on a single filing take FILE=<id>,
# optionally with YEAR=<yyyy>, ROLE=<role_short>, DATE=<yyyy-mm-dd>.
# Use `make help` for a full list.

.DEFAULT_GOAL := help

.PHONY: help \
        install format lint test setup-check clean \
        extract extract-all extract-force extract-facts \
        summary statements render verify \
        clean-output log-tail log-failures

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

help:
	@echo ""
	@echo "Project commands:"
	@echo "  install            pip install -e \".[dev]\""
	@echo "  format             black src tests scripts"
	@echo "  lint               ruff check src tests scripts --fix"
	@echo "  test               pytest"
	@echo "  setup-check        pytest tests/test_setup.py -v"
	@echo "  clean              remove build artifacts and caches"
	@echo ""
	@echo "Extraction:"
	@echo "  extract FILE=path/to/file.zip"
	@echo "                     Extract a single zip (all 5 outputs)."
	@echo "  extract-all        Extract every zip in data/input/ (skip those already done)."
	@echo "  extract-force      Re-extract everything in data/input/ (ignore idempotency)."
	@echo "  extract-facts      Extract every zip, .facts.json only (no linkbases)."
	@echo "                     Add FILE=... to limit to one zip."
	@echo ""
	@echo "Inspection (FILE=<company_id> like 1860 for Apple):"
	@echo "  summary    FILE=1860 [YEAR=2025]"
	@echo "                     One-page overview of the filing."
	@echo "  statements FILE=1860 [YEAR=2025]"
	@echo "                     List role_short values available in the filing."
	@echo "  render     FILE=1860 ROLE=CONSOLIDATEDBALANCESHEETS [YEAR=2025] [DATE=2025-09-27]"
	@echo "                     Render a statement as indented text."
	@echo "  verify     FILE=1860 ROLE=CONSOLIDATEDBALANCESHEETS [YEAR=2025] [DATE=2025-09-27] [TOLERANCE=0]"
	@echo "                     Verify calc arithmetic against actual facts."
	@echo ""
	@echo "Logs & cleanup:"
	@echo "  clean-output       Wipe data/output/ (forces fresh re-extraction next run)."
	@echo "  log-tail           tail -f logs/run_log.jsonl"
	@echo "  log-failures       jq for non-success log records."
	@echo ""

# ---------------------------------------------------------------------------
# Dev / project
# ---------------------------------------------------------------------------

install:
	pip install -e ".[dev]"

format:
	black src tests scripts

lint:
	ruff check src tests scripts --fix

test:
	pytest

setup-check:
	pytest tests/test_setup.py -v

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

# extract FILE=path/to/zip
# Required: FILE
extract:
	@test -n "$(FILE)" || (echo "Usage: make extract FILE=path/to/file.zip"; exit 1)
	python -m xbrl_extraction "$(FILE)"

# extract-all — every zip in data/input/, idempotent
extract-all:
	python -m xbrl_extraction data/input/

# extract-force — every zip, ignore idempotency, overwrite outputs
extract-force:
	python -m xbrl_extraction data/input/ --force

# extract-facts — facts.json only (no linkbase outputs)
# Optional: FILE=path/to/zip (single-file mode)
extract-facts:
	@if [ -n "$(FILE)" ]; then \
		python -m xbrl_extraction "$(FILE)" --facts-only; \
	else \
		python -m xbrl_extraction data/input/ --facts-only; \
	fi

# ---------------------------------------------------------------------------
# Inspection (via scripts/inspect_filings.py)
# ---------------------------------------------------------------------------

# Build the YEAR=... arg only when set
_YEAR_ARG = $(if $(YEAR),--year $(YEAR),)
_DATE_ARG = $(if $(DATE),--date $(DATE),)
_TOL_ARG  = $(if $(TOLERANCE),--tolerance $(TOLERANCE),)

summary:
	@test -n "$(FILE)" || (echo "Usage: make summary FILE=<company_id> [YEAR=<yyyy>]"; exit 1)
	python scripts/inspect_filings.py summary --file $(FILE) $(_YEAR_ARG)

statements:
	@test -n "$(FILE)" || (echo "Usage: make statements FILE=<company_id> [YEAR=<yyyy>]"; exit 1)
	python scripts/inspect_filings.py statements --file $(FILE) $(_YEAR_ARG)

render:
	@test -n "$(FILE)" || (echo "Usage: make render FILE=<company_id> ROLE=<role_short> [YEAR=<yyyy>] [DATE=<yyyy-mm-dd>]"; exit 1)
	@test -n "$(ROLE)" || (echo "Usage: make render FILE=<company_id> ROLE=<role_short> [YEAR=<yyyy>] [DATE=<yyyy-mm-dd>]"; exit 1)
	python scripts/inspect_filings.py render --file $(FILE) --role $(ROLE) $(_YEAR_ARG) $(_DATE_ARG)

verify:
	@test -n "$(FILE)" || (echo "Usage: make verify FILE=<company_id> ROLE=<role_short> [YEAR=<yyyy>] [DATE=<yyyy-mm-dd>] [TOLERANCE=<float>]"; exit 1)
	@test -n "$(ROLE)" || (echo "Usage: make verify FILE=<company_id> ROLE=<role_short> [YEAR=<yyyy>] [DATE=<yyyy-mm-dd>] [TOLERANCE=<float>]"; exit 1)
	python scripts/inspect_filings.py verify --file $(FILE) --role $(ROLE) $(_YEAR_ARG) $(_DATE_ARG) $(_TOL_ARG)

# ---------------------------------------------------------------------------
# Logs & cleanup
# ---------------------------------------------------------------------------

clean-output:
	rm -f data/output/*.json

log-tail:
	tail -f logs/run_log.jsonl

log-failures:
	@if [ -f logs/run_log.jsonl ]; then \
		jq 'select(.status != "success")' logs/run_log.jsonl; \
	else \
		echo "No log file yet."; \
	fi
