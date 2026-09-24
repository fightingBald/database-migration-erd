# Developer guide

## Use inside an existing project

Copy only `erd_generator/`, `requirements.txt` and `.gitignore` into `tools/erd-generator/`. Follow the [README installation steps](README.md#install) there, then call from your existing codegen script:

```bash
PYTHONPATH=./tools/erd-generator \
  ./tools/erd-generator/.venv/bin/python -m erd_generator \
  ./db/migrations ./docs-site/static/img/schema.svg
```

Replace the input/output paths and propagate the exit code. D2 0.7.1 must be on PATH.

Ignore outputs outside the tool directory in the **parent project's** `.gitignore`:

```gitignore
/docs-site/static/img/schema.svg
/docs-site/static/img/schema.partial.svg
```

## CI and Docusaurus

Install dependencies and D2 → run codegen → build Docusaurus → deploy. Stop on codegen failure; never publish partial previews. Pass generated images between jobs as artifacts, without committing them to Git.

Reference the generated file under `docs-site/static/img/`:

```markdown
![Database schema](/img/schema.svg)

[Open full size](/img/schema.svg)
```

Adjust URLs for the site's `baseUrl`.

## Relationships without database FK constraints

SQL foreign keys are loaded automatically. Column comments such as `-- FK demo_library.members(id)` also declare relationships. Add more with `--fk-config ./fk.yaml`:

```yaml
demo_library.loans:
  fks:
    - [member_id, demo_library.members, id]
    - [book_id, demo_library.books, id]
```

Entries are `[local_column, target_table, target_column]`; composite keys use lists: `[[tenant_id, member_id], demo_library.members, [tenant_id, id]]`. Tables and columns must exist, and short names must be unambiguous. Duplicates are deduplicated. SQL `REFERENCES table` without target columns can infer only a single-column primary key.

## Business layout

Table names and FK relationships suggest groups automatically. To set membership, titles or colours, pass `--layout-config ./erd-layout.yaml`:

```yaml
groups:
  books:
    tables: ["demo_library.books", "demo_library.book_*"]
    label: Books
    color: blue
  loans:
    tables: ["demo_library.loans"]
    color: gold
```

Only `tables` is required. Exact names take precedence over case-sensitive wildcards; unmatched selectors and overlapping groups are errors. Remaining tables are grouped automatically. Colours: `blue`, `gold`, `green`, `violet`, `slate`, `rose`, `teal`, `orange`.

ELK refinement can lay out clusters independently, pack their measured rectangles and route cross-group arrows. It accepts only verified improvements; failures retain native layout. A smaller canvas may have more crossings. Use `--grouping none` to disable automatic grouping/refinement while retaining configured groups.

`--show-references` labels cross-group FK targets beside fields. `--hide-types` and `--hide-indexes` reduce detail.

## Optional TALA layout

Install `d2plugin-tala` on PATH using the [upstream setup and licensing instructions](https://github.com/terrastruct/TALA). Tested with D2 0.7.1 and TALA 0.4.3:

```bash
d2 layout tala
python -m erd_generator ./migrations ./generated/schema.svg --layout tala
```

A missing or failing plugin reports an error; it never silently switches engines.

## Explicit D2 source export

`python -m erd_generator ./migrations ./generated/schema.d2` exports source without requiring D2. Add `--render svg` to retain both source and image.

Intermediate layouts stay in memory; only final publication uses an atomic staging file. D2 exports contain the native graph, so Preview may differ from the refined SVG. View SVGs in a browser: index captions use `foreignObject`, unsupported by some converters.

## SQL support and diagnostics

Inputs are UTF-8. `V<number>__description.sql` files use numeric version order; other SQL files use path order. sql-migrate/goose files read only Up sections; `.down.sql` files are skipped.

| SQL | Handling |
| --- | --- |
| `CREATE TABLE`, common `ALTER TABLE`, `DROP TABLE` | Apply table, column and constraint changes. |
| Create/drop/rename indexes | Preserve ordinary, unique, expression and partial index metadata. Unknown table targets are errors. |
| Views and materialized views | Exclude from ERD; skip indexes only for explicitly recorded materialized views. |
| Roles, permissions, standalone schemas | Skip supported setup commands, including verified role/permission `DO` blocks. |
| Function/procedure definitions, top-level `CALL`, `DROP PROCEDURE`, `CREATE EXTENSION` | Skip without executing or inferring side effects. |
| Straight-line `DO` blocks | Apply supported static table/index DDL. |
| Unsupported conditional/dynamic structural SQL | Report an error, roll back the affected statement/block and continue scanning. |

SQL is never executed. Enums, partitioning, `search_path`, view dependencies and routine/extension side effects are not modeled. Use qualified names and ordinary DDL or a reviewed snapshot for procedurally created structures. Python callers parsing chunks must share a `SQLParseContext`; `load_schema_result()` manages this automatically.

Diagnostics go to **stderr**; `--log-dir PATH` additionally saves them under `PATH/parse_log/`.

On SQL/schema/FK errors, valid tables may produce an **INCOMPLETE** `.partial.svg` (or `.partial.d2` for source requests). Invalid relationships and layout overrides are omitted; files with unclosed quotes/blocks are skipped. Each run clears stale partial outputs.

Failures preserve the previous SVG. Exit codes: **0** success, **1** generation failure, **2** invalid options. Source and SVG are published atomically as separate files, not as one transaction.

## Development

Tests live under `tests/{unit,cli,integration}/`, with shared helpers in `tests/support/` and fictional SQL in `tests/fixtures/`. Keep tests and generated files out of the copied runtime.

```bash
python -m pip install -r requirements-dev.txt
python -m compileall -q erd_generator
python -m pytest -q -m 'not integration'
python -m ruff check .
python -m ruff format --check .
python -m pytest -q -m integration
```

CI checks Python 3.11/3.14. Rendering tests require D2 0.7.1; optional TALA tests skip without the plugin (`python -m pytest -q -m tala`).

Flow: SQL/FK YAML → Schema → D2 → render → optional cluster composition → verified SVG. Lower-level modules must not import the CLI.

| Responsibility | Entry points |
| --- | --- |
| CLI and file outputs | [cli.py](erd_generator/cli.py), [artifacts.py](erd_generator/artifacts.py) |
| SQL and configuration | [sql_parser.py](erd_generator/sql_parser.py), [fk_config.py](erd_generator/fk_config.py), [layout_config.py](erd_generator/layout_config.py) |
| Schema and validation | [schema.py](erd_generator/schema.py), [validation.py](erd_generator/validation.py) |
| Pure D2 generation | [d2.py](erd_generator/d2.py) and its layout/style/serialization helpers |
| Rendering and refinement | [d2_renderer.py](erd_generator/d2_renderer.py), [d2_refinement.py](erd_generator/d2_refinement.py), [d2_geometry.py](erd_generator/d2_geometry.py) |
| SVG composition | [svg_partitions.py](erd_generator/svg_partitions.py), [diagram_packing.py](erd_generator/diagram_packing.py), [diagram_routing.py](erd_generator/diagram_routing.py), [d2_index_svg.py](erd_generator/d2_index_svg.py) |
