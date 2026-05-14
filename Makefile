.PHONY: install format lint test setup-check clean run-sample

install:
	pip install -e ".[dev]"

# format:
# 	black .
format:
	black src tests

# lint:
# 	ruff check . --fix
lint:
	ruff check src tests --fix

test:
	pytest

setup-check:
	pytest tests/test_setup.py -v

clean:
	rm -rf build dist *.egg-info .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

# Convenience: process every zip in data/input/
run-sample:
	python -m xbrl_extraction data/input/