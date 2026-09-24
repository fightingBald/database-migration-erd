# Developer guide

See the [README](README.md) for installation and basic usage; `python -m erd_generator --help` lists all options.

## Use inside an existing project

Copy `erd_generator/`, `requirements.txt` and `.gitignore` into `tools/erd-generator/`. The Python package contains only runtime code. Exclude `tests/`, `.git/`, virtual environments, caches, local SQL and generated files; `.gitignore` does not filter filesystem copies.

Follow the README installation steps inside that directory. From the parent project's existing codegen script:

```bash
PYTHONPATH=./tools/erd-generator \
  ./tools/erd-generator/.venv/bin/python -m erd_generator \
  ./db/migrations ./docs-site/static/img/schema.svg
```

Replace the input/output paths and propagate the exit code. D2 0.7.1 must be on PATH. No wrapper or extra build configuration is needed.

The tool's `.gitignore` applies inside its directory. Ignore external outputs in the **parent project's** `.gitignore`:

```gitignore
/docs-site/static/img/schema.svg
/docs-site/static/img/schema.partial.svg
```

Untrack existing generated files with `git rm --cached -- <generated-path>`.

## CI and Docusaurus

Install dependencies and D2 → run codegen with the complete migration history → build Docusaurus → deploy. Stop the documentation build if codegen fails; do not publish partial previews. Generated images need no Git commit. Separate build/deploy jobs should pass artifacts from the same successful run.

Reference the generated file under `docs-site/static/img/`:

```markdown
![Database schema](/img/schema.svg)

[Open full size](/img/schema.svg)
```

Check the image URL against the site's configured `baseUrl` before publishing.

## Relationships without database FK constraints

SQL foreign keys are loaded automatically. Column comments such as `-- FK demo_library.members(id)` also declare relationships. Add more with `--fk-config ./fk.yaml`:

```yaml
demo_library.loans:
  fks:
    - [member_id, demo_library.members, id]
    - [book_id, demo_library.books, id]
```

Each entry is `[local_column, target_table, target_column]`. Composite keys use lists: `[[tenant_id, member_id], demo_library.members, [tenant_id, id]]`.

Tables and columns must exist; short table names must resolve unambiguously. Prefer schema-qualified names. YAML supplements SQL relationships; duplicates are deduplicated. For SQL `REFERENCES table` without target columns, only a single-column primary key can be inferred.

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

Only `tables` is required. Selectors match exact names before case-sensitive wildcards; unmatched selectors and overlapping groups are errors. Colours: `blue`, `gold`, `green`, `violet`, `slate`, `rose`, `teal`, `orange`. Remaining tables are grouped automatically.

Use `--grouping none` to disable automatic grouping/refinement while retaining configured groups. `--show-references` labels cross-group FK targets beside fields. `--hide-types` and `--hide-indexes` reduce detail.

Layout refinement keeps a candidate only when measured SVG geometry improves without breaking its checks; dense graphs can still have long lines. Implementation: [grouping](erd_generator/d2_business.py), [colour selection](erd_generator/d2_styles.py), [refinement and acceptance checks](erd_generator/d2_refinement.py).

ELK also tries one cluster-level plan using measured region sizes, within a maximum of five renders. It changes ordering and edge orientation while ELK retains field routing; it does not freeze cluster coordinates or put cross-group edges in grids. This candidate requires at least 10% less canvas area, allows at most 3% more total line length, and cannot increase the longest line, longest canvas side or average cluster distance. Failed or worse candidates retain the previous winner. No additional CLI options are required; `--grouping none` disables refinement.

## Optional TALA layout

Install `d2plugin-tala` on PATH using the [upstream setup and licensing instructions](https://github.com/terrastruct/TALA). Tested with D2 0.7.1 and TALA 0.4.3:

```bash
d2 layout tala
python -m erd_generator ./migrations ./generated/schema.svg --layout tala
```

Manage the plugin and any required credentials in your environment. A missing or failing plugin reports an error; it never silently switches engines. Omit `--layout tala` to use ELK.

## Explicit D2 source export

`python -m erd_generator ./migrations ./generated/schema.d2` exports source without requiring D2. Add `--render svg` to retain both source and image.

SVG requests use temporary source and leave existing `.d2` files untouched. Scripts that used the former automatic sidecar must request it explicitly. Native D2 Preview can differ from the exported SVG, which also applies rendering options and index-caption alignment. View SVGs in a browser; captions use `foreignObject`, unsupported by some converters.

## SQL support and diagnostics

Inputs are UTF-8. `V<number>__description.sql` files use numeric version order; other SQL files use path order. sql-migrate/goose files read only Up sections; `.down.sql` files are skipped. Supply all migrations needed to build the schema.

| SQL | Handling |
| --- | --- |
| `CREATE TABLE`, common `ALTER TABLE`, `DROP TABLE` | Apply table, column and constraint changes. |
| Create/drop/rename indexes | Preserve ordinary, unique, expression and partial index metadata. Unknown table targets are errors. |
| Views and materialized views | Exclude from ERD; skip indexes only for explicitly recorded materialized views. |
| Roles, permissions, standalone schemas | Skip supported setup commands, including verified role/permission `DO` blocks. |
| Function/procedure definitions, top-level `CALL`, `DROP PROCEDURE`, `CREATE EXTENSION` | Skip without executing or inferring side effects. |
| Straight-line `DO` blocks | Apply supported static table/index DDL. |
| Unsupported conditional/dynamic structural SQL | Report an error, roll back the affected statement/block and continue scanning. |

SQL is never executed. Enums, partitioning, `search_path`, view dependencies and routine/extension side effects are not modeled. Use consistent qualified names; use ordinary DDL or a reviewed snapshot for structures created through unsupported procedural code. No diagnostics does not guarantee complete PostgreSQL interpretation. Python callers parsing separate chunks must share a `SQLParseContext`; `load_schema_result()` manages this automatically.

Diagnostics go to **stderr only** by default. Add `--log-dir PATH` to also save them under `PATH/parse_log/`; `--log-dir .` restores the previous default. Remove an existing `--log-dir` argument from codegen to disable file logging.

On SQL/schema/FK errors, valid content may produce an **INCOMPLETE** `.partial.svg`; formal outputs are preserved and the exit code is **1**. Invalid relationships are omitted, layout overrides are ignored, and files with unclosed quotes/blocks are skipped. No drawable tables means no preview. Each run clears stale partial outputs. Explicit source requests use `.partial.d2`.

Rendering failures also preserve the previous SVG. Check `d2 --version`, `--d2-binary PATH` or `--render-timeout SECONDS` as appropriate. Exit codes: **0** success, **1** generation failure, **2** invalid options. SVG publication is atomic; when both source and SVG are requested, their replacements are separate operations.

## Development

All tests live under `tests/`: `unit/` for modules, `cli/` for command-line/codegen contracts, and `integration/` for real rendering. Shared helpers live in `support/`; SQL fixtures live in `fixtures/`. Test modules import shared helpers, never other test modules.

```bash
python -m pip install -r requirements-dev.txt
python -m compileall -q erd_generator
python -m pytest -q -m 'not integration'
python -m ruff check .
python -m ruff format --check .
python -m pytest -q -m integration
```

CI checks Python 3.11/3.14 and pinned ELK rendering. Integration tests require D2 0.7.1. Optional TALA tests skip when the plugin is absent; run them with `python -m pytest -q -m tala`. Use fictional fixtures and keep generated files out of Git.

Dependency flow: SQL/FK YAML → Schema → D2 source → renderer → SVG. Lower-level modules must not import the CLI.

| Responsibility | Entry points |
| --- | --- |
| CLI and file outputs | [cli.py](erd_generator/cli.py), [artifacts.py](erd_generator/artifacts.py) |
| SQL and configuration | [sql_parser.py](erd_generator/sql_parser.py), [fk_config.py](erd_generator/fk_config.py), [layout_config.py](erd_generator/layout_config.py) |
| Schema and validation | [schema.py](erd_generator/schema.py), [validation.py](erd_generator/validation.py) |
| Pure D2 generation | [d2.py](erd_generator/d2.py) and its layout/style/serialization helpers |
| Rendering and refinement | [d2_renderer.py](erd_generator/d2_renderer.py), [d2_refinement.py](erd_generator/d2_refinement.py), [d2_geometry.py](erd_generator/d2_geometry.py), [d2_index_svg.py](erd_generator/d2_index_svg.py) |
