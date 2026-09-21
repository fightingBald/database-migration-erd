# Developer guide

See the [README](README.md) for installation and everyday use. This guide covers project integration, configuration and development. For the full CLI reference, run `python -m erd_generator --help`.

## Use inside an existing project

Copy the source, dependency files, tests and `.gitignore` into `tools/erd-generator/`. Exclude the original `.git/`, virtual environments, local SQL and generated files; `.gitignore` does not filter a filesystem copy.

Follow the README installation steps inside that directory. From the parent project's root, call this from its existing codegen script:

```bash
PYTHONPATH=./tools/erd-generator \
  ./tools/erd-generator/.venv/bin/python -m erd_generator \
  ./db/migrations ./docs-site/static/img/schema.svg \
  --log-dir ./tools/erd-generator
```

Replace the SQL and output paths, and propagate a nonzero exit code. Rendering requires **D2 0.7.1** with bundled ELK; `.d2` output alone needs no D2 executable.

Keep the tool's `.gitignore`; its rooted rules apply inside `tools/erd-generator/`, so they do not ignore the parent project's migrations. Add outputs outside that directory to the **parent project's** `.gitignore`:

```gitignore
/docs-site/static/img/schema.svg
/docs-site/static/img/schema.d2
```

For already tracked outputs, use `git rm --cached -- <generated-path>` to untrack them while keeping local files.

## CI and Docusaurus

Use this order in the application's existing pipeline:

```text
Install Python dependencies + D2 0.7.1 → run codegen → build Docusaurus → deploy site
```

Use the complete migration history from the CI checkout. With the embedded tool above, codegen uses the same command locally and in CI. Run generation before every documentation build and ensure SQL changes trigger the pipeline. No database connection or Docusaurus plugin is required.

In a Docusaurus Markdown page, reference the generated file under `docs-site/static/img/`:

```markdown
![Database tables and relationships](/img/schema.svg)

[Open the full-size diagram](/img/schema.svg)
```

Treat `.svg` and `.d2` as build outputs; CI does not need to commit them. Stop the job if generation fails. PRs can validate generation and the site build; the deployment job publishes the resulting site. If these are separate jobs, pass artifacts from the same run and require the previous job to succeed. Verify the image under the site's configured `baseUrl` before publishing.

## Relationships without database FK constraints

SQL foreign keys are loaded automatically. Column comments such as `-- FK demo_library.members(id)` can also declare relationships. To add relationships in YAML, pass `--fk-config ./fk.yaml`:

```yaml
demo_library.loans:
  fks:
    - [member_id, demo_library.members, id]
    - [book_id, demo_library.books, id]
```

Each entry is `[local_column, target_table, target_column]`. For composite keys, use lists on both sides: `[[tenant_id, member_id], demo_library.members, [tenant_id, id]]`.

Names and columns must exist; short table names must resolve unambiguously. Prefer qualified names when multiple schemas share table names. YAML adds relationships without replacing SQL declarations; duplicate relationships are deduplicated.

For SQL `REFERENCES table` without target columns, only a single-column primary key can be inferred. Specify target columns explicitly for composite keys.

## Business layout

Grouping is automatic: table-name families and FK connectivity suggest regions, stable group identifiers select colours, and disconnected components are packed together. These are presentation heuristics; inferred groups may need correction and dense graphs can still have long or crossing lines.

To override membership, titles or colours, pass `--layout-config ./erd-layout.yaml`:

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

Only `tables` is required. `label` defaults to the group key. Available colours: `blue`, `gold`, `green`, `violet`, `slate`, `rose`, `teal`, `orange`.

Selectors match exact qualified table names first, then case-sensitive wildcards. Every selector must match; overlapping groups, duplicate keys and invalid configuration fail generation. Remaining tables are grouped automatically. `--grouping none` disables automatic grouping but retains explicit groups.

`--show-references` adds labels such as `FK → members.id` beside source fields for relationships between top-level groups. It retains the arrows and can widen tables; it is off by default.

SVG generation may compare one additional ELK layout and select a more compact result after geometry and relationship checks. Successful output includes its matching D2 source. Source-only generation writes the initial layout. Algorithm details live in the [layout modules](#code-map) and their tests.

## SQL support and diagnostics

Inputs must be UTF-8. `V<number>__description.sql` migrations are ordered by numeric version; other SQL files follow in path order. The diagram describes the supplied migrations, not a live database or migration execution history.

| SQL input | Behavior |
| --- | --- |
| `CREATE TABLE`, common `ALTER TABLE`, `DROP TABLE` and column/constraint changes | Update the schema. |
| `CREATE INDEX`, `DROP INDEX`, `ALTER INDEX ... RENAME` | Update index metadata, including expression/partial index notes. |
| `GRANT`, `REVOKE`, `ALTER DEFAULT PRIVILEGES`, `CREATE ROLE/USER`, standalone `CREATE SCHEMA` | Ignore supported setup commands that do not change ERD objects. |
| Function/procedure definitions with string or dollar-quoted bodies | Ignore the definition; never execute the body. |
| Straight-line `DO` blocks | Apply supported static table/index DDL; dollar-quoted bodies stay intact. |
| Known role/permission `DO` blocks using `IF` or constant `EXECUTE format(...)` | Ignore only after every branch and command is checked as ERD-neutral. |
| Conditional/dynamic structural DDL, loops, calls or unsupported procedural constructs | Report a diagnostic and stop generation. |

The tool does not execute SQL. Unsupported procedural migrations need ordinary DDL or a reviewed schema snapshot as input. See the [role setup fixture](tests/fixtures/postgres_role_setup.sql) for an accepted block and [the block checker](erd_generator/postgres_do.py) for exact rules.

Views, enums, partitioning, `search_path` and some other PostgreSQL features are not fully modeled. Zero diagnostics does not guarantee complete PostgreSQL interpretation. Self-referencing arrows may attach to table boundaries in D2/ELK; their field names remain explicit in labels.

Tables show PK/FK markers and UNQ for unconditional single-column unique constraints/indexes. Full relationship and index details appear in tooltips; `--force-appendix` makes those notes visible in the SVG.

| Problem | What to check |
| --- | --- |
| SQL/configuration error | Read the reported file/object and `parse_log/` diagnostics; fix the input before regenerating. Existing outputs are preserved. |
| D2 missing or wrong version | Install exactly 0.7.1, check `d2 --version`, or set `--d2-binary`. |
| Rendering failure | The new D2 source is retained and the previous SVG is unchanged. Fix the error and rerun. |
| Timeout | Inspect diagram size and increase `--render-timeout` if needed. |

Exit codes: **0** success, **1** generation/rendering failure, **2** invalid options. Source and SVG replacement are separate operations, so automation must check the exit code. Processing runs locally; no SQL or diagram is uploaded.

## Additional CLI options

Common display options are in the README; `--help` lists all options.

| Option | Purpose |
| --- | --- |
| `--d2-binary PATH` | Rendering executable; defaults to `d2`. |
| `--render-timeout SECONDS` | Positive timeout per D2 process; default 120. Layout comparison may use two processes. |
| `--force-appendix` | Include table tooltip notes in the SVG appendix. |
| `--log-dir PATH` | Write diagnostics to `PATH/parse_log/`; defaults to the working directory. |

The first three options require SVG rendering.

## Development

After activating the README's Python environment:

```bash
python -m pip install -r requirements-dev.txt
python -m compileall -q erd_generator
python -m pytest -q -m 'not integration'
python -m ruff check .
python -m ruff format --check .
python -m pytest -q -m integration
```

Fast tests do not require D2. Integration tests require exactly D2 0.7.1 with ELK and fail if it is unavailable. Unit tests live beside their modules; CLI and rendering tests live under `tests/`. Use synthetic fixtures only; keep company SQL, local research and generated diagrams out of Git.

### Code map

```text
SQL + optional FK YAML → Schema → D2 source → D2 / ELK → SVG
```

| Responsibility | Modules |
| --- | --- |
| CLI and orchestration | [cli.py](erd_generator/cli.py) |
| SQL loading and diagnostics | [sql_parser.py](erd_generator/sql_parser.py), `sql_statements.py`, `postgres_commands.py`, `postgres_do.py`, `diagnostics.py` |
| Schema and configuration | [schema.py](erd_generator/schema.py), `validation.py`, `fk_config.py`, `layout_config.py` |
| Pure layout and D2 generation | [d2.py](erd_generator/d2.py), `d2_business.py`, `d2_grouping.py`, `d2_layout.py`, `d2_emit.py`, `d2_references.py`, `d2_styles.py` |
| Rendering and layout comparison | [d2_renderer.py](erd_generator/d2_renderer.py), `d2_refinement.py`, `d2_geometry.py` |
| Atomic source publication | [artifacts.py](erd_generator/artifacts.py) |

CLI loads inputs and coordinates generation. Planners operate on Schema without I/O or mutation; the renderer does not depend on Schema or planners. `d2_refinement` coordinates rendering candidates and geometry checks. Lower-level modules must not import the coordinator or CLI.
