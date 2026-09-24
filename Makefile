PYTHON ?= .venv/bin/python

.PHONY: build test test-integration lint format
build:
	$(PYTHON) -m compileall -q erd_generator
	$(PYTHON) -m build --no-isolation

test:
	$(PYTHON) -m pytest -q -m 'not integration'

test-integration:
	$(PYTHON) -m pytest -q -m integration

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff format .
