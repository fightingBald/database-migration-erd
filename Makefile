PYTHON ?= .venv/bin/python
MIGRATIONS ?= db/migration
SOURCE ?= generated/schema.d2
FK_CONFIG ?= sample_fk_config.yaml
STYLE ?= clean
DIAGRAM_ARGS = --migrations "$(MIGRATIONS)" --out "$(SOURCE)" --show-types --style "$(STYLE)" $(if $(FK_CONFIG),--fk-config "$(FK_CONFIG)",)

.PHONY: build gen run test test-integration lint format benchmark
build:
	$(PYTHON) -m compileall -q erd_generator scripts gen_drawio_erd_table.py parse_drawio_edges.py compare_drawio_to_migrations.py

gen:
	$(PYTHON) -m erd_generator $(DIAGRAM_ARGS)

run:
	$(PYTHON) -m erd_generator $(DIAGRAM_ARGS) --render svg

test:
	$(PYTHON) -m pytest -q -m 'not integration'

test-integration:
	$(PYTHON) -m pytest -q -m integration

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff format .

benchmark:
	$(PYTHON) scripts/benchmark_rendering.py --tables 50
	$(PYTHON) scripts/benchmark_rendering.py --tables 200
