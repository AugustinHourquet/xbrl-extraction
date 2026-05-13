.PHONY: install format lint test setup-check

install:
	pip install -e ".[dev]"

format:
	black .

lint:
	ruff check . --fix

test:
	pytest

setup-check:
	pytest tests/test_setup.py -v