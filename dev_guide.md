# Developer guide

See the [README](README.md) for installation and everyday use. This guide covers project integration, configuration and development. For the full CLI reference, run `python -m erd_generator --help`.

## Use inside an existing project

Runtime needs only `erd_generator/`, `requirements.txt` and `.gitignore` copied into `tools/erd-generator/`. Keep tests and development files only if you plan to modify the tool. Exclude the original `.git/`, virtual environments, local SQL and generated files; `.gitignore` does not filter a filesystem copy. No wrapper, Makefile or extra configuration is required.

Follow the README installation steps inside that directory. From the parent project's root, call this from its existing codegen script:

```bash
PYTHONPATH=./tools/erd-generator \
  ./tools/erd-generator/.venv/bin/python -m erd_generator \
  ./db/migrations ./docs-site/static/img/schema.svg \
  --log-dir ./tools/erd-generator
```

Replace the SQL and output paths, and propagate a nonzero exit code. Rendering requires **D2 0.7.1**; bundled ELK is the default. `.d2` output alone needs no D2 executable.

Keep the tool's `.gitignore`; its rooted rules apply inside `tools/erd-generator/`, so they do not ignore the parent project's migrations. Add outputs outside that directory to the **parent project's** `.gitignore`:

```gitignore
/docs-site/static/img/schema.svg
/docs-site/static/img/schema.d2
/docs-site/static/img/schema.partial.svg
/docs-site/static/img/schema.partial.d2
```

For already tracked outputs, use `git rm --cached -- <generated-path>` to untrack them while keeping local files.

## Optional TALA layout

Install `d2plugin-tala` on PATH using the [official instructions](https://github.com/terrastruct/TALA). Tested with **D2 0.7.1 + TALA 0.4.3**:

```bash
d2 layout tala
python -m erd_generator ./migrations ./generated/schema.svg --layout tala
```

Add the same `--layout tala` option to your existing codegen command. Groups, colours, FK labels, index footers and cluster proximity refinement work with either engine. ELK-specific rank adjustments stay disabled for TALA. Source-only `.d2` output records the selected engine and needs no plugin. Omit `--layout` or use `--layout elk` to switch back.

TALA is closed-source: commercial use requires a license, and evaluation output has a watermark. Its [upstream repository](https://github.com/terrastruct/TALA) was archived in September 2026. Keep its binary/version managed by your environment; the tool does not download it. Upstream licensing uses `TSTRUCT_TOKEN` or an auth file (`TSTRUCT_AUTHFILE`); these are preserved for D2. In CI, supply credentials through the existing secret mechanism. Ambient `D2_*`, `ELK_*` and `TALA_*` overrides are ignored; TALA uses seeds `1,2,3`. Missing or failing TALA never silently switches to ELK, and rendering failure preserves the previous SVG.

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

Treat `.svg` and `.d2` as build outputs; CI does not need to commit them. Propagate codegen's exit code and stop the documentation build on failure. Partial previews and `parse_log/` can be retained as diagnostic artifacts, never as the published diagram. If generation and deployment are separate jobs, pass artifacts from the same run and require generation to succeed. Verify the image under the site's configured `baseUrl` before publishing.

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

SVG generation keeps the existing layout as its baseline, including ELK's optional compact pass. With at least 12 tables and two distinct cross-group links, it then tries at most two proximity candidates: weighted group order, and disjoint strongly connected pairs in transparent containers. Each distinct FK constraint has weight 1; a composite FK counts once. Group membership, colours and all FK arrows are preserved.

Small ordering problems use exhaustive search (up to 7 ranks); larger ones use at most 8 adjacent-swap improvements. Pairing maximizes total FK weight for up to 12 linked groups, then uses deterministic greedy matching for larger graphs. ELK can also reorder its existing rank classes; TALA receives the group declaration order without ELK rank rules.

Selection uses verified native SVG geometry: FK-weighted mean Manhattan distance between group centres must fall by at least 5%. Canvas area, longest canvas side, total route length and longest route cannot increase; aspect ratio stays within the previous ratio or 2. The crossing proxy allows at most 5% more crossings (2 on small diagrams). Both candidates are compared with the same baseline. A failed or worse candidate keeps the previous winner; unverifiable baseline geometry skips refinement. Appendices and partial previews use one pass.

Successful output includes D2 source and SVG with native table and FK geometry. Index captions receive the alignment adjustment described below. Source-only generation writes the initial layout. Regenerate diagrams after upgrading; `--grouping none` disables automatic refinement while retaining explicit groups. Reverting the tool revision restores the previous automatic layout. Generated object paths may change with container placement.

## SQL support and diagnostics

Inputs must be UTF-8. `V<number>__description.sql` migrations are ordered by numeric version; other SQL files follow in path order. The diagram describes the supplied migrations, not a live database or migration execution history.

Plain SQL is read in full. For sql-migrate/goose files, only the Up section is read; direction markers are case-insensitive, and text inside SQL literals, comments or routine bodies is preserved. `.down.sql` files are skipped before reading. Missing Down is allowed; Down without Up, repeated Up, mixed marker formats or SQL before Up produce a diagnostic. Other migration-framework directives are not interpreted. Regenerate existing diagrams after upgrading to exclude rollback changes; reverting the tool revision restores the previous behavior.

| SQL input | Behavior |
| --- | --- |
| `CREATE TABLE`, common `ALTER TABLE`, `DROP TABLE` and column/constraint changes | Update the schema. |
| `CREATE INDEX`, `DROP INDEX`, `ALTER INDEX ... RENAME` | Update index metadata, including expression/partial index notes. |
| `GRANT`, `REVOKE`, `ALTER DEFAULT PRIVILEGES`, `CREATE ROLE/USER`, standalone `CREATE SCHEMA` | Ignore supported setup commands that do not change ERD objects. |
| `CREATE VIEW` | Skip the definition and query. |
| `CREATE MATERIALIZED VIEW`, `DROP MATERIALIZED VIEW` | Track explicitly created/dropped names across files; skip indexes only for recorded materialized views. Unknown index targets still fail. |
| Function/procedure definitions, including `= defaults`, quoted and `BEGIN ATOMIC` bodies | Skip the complete definition before syntax parsing; never execute the body. |
| Top-level `CALL`, `DROP PROCEDURE`, `CREATE EXTENSION` | Skip; do not infer their effects on tables. |
| Straight-line `DO` blocks | Apply supported static table/index DDL; dollar-quoted bodies stay intact. |
| Known role/permission `DO` blocks using `IF` or constant `EXECUTE format(...)` | Ignore only after every branch and command is checked as ERD-neutral. |
| Conditional/dynamic structural DDL, loops, calls inside `DO` or unsupported procedural constructs | Report a diagnostic; roll back the statement/block and continue scanning. |

The tool does not execute SQL. Unsupported procedural migrations need ordinary DDL or a reviewed schema snapshot as input. See the [role setup fixture](tests/fixtures/postgres_role_setup.sql) for an accepted block and [the block checker](erd_generator/postgres_do.py) for exact rules.

View queries/dependencies, routine/extension side effects, enums, partitioning and `search_path` are not modeled. Use consistent qualified names for materialized views and their indexes; no short-name matching is attempted. Supply ordinary DDL or a reviewed snapshot for tables created through calls/extensions. Zero diagnostics does not guarantee complete PostgreSQL interpretation. Self-referencing arrows may attach to table boundaries in D2/ELK; their field names remain explicit in labels.

Python callers applying separate SQL chunks must share a `SQLParseContext` through `parse_schema_from_sql(..., context=...)`; `load_schema_result()` manages this automatically. Regenerate diagrams after upgrading; rolling back the tool revision restores the previous rejection policy.

Errors produce an **INCOMPLETE** preview when drawable tables remain, with exit code **1** and the requested outputs unchanged. Invalid tables and unresolved relationships are omitted and reported in `parse_log/`; a file with unclosed quotes or block boundaries is skipped. Previews use one pass of the selected engine without layout overrides. Source-only requests create only `.partial.d2`. Each run clears the previous `.partial` pair, so stale previews are not reused. Known skipped commands are summarized in the log.

Tables show PK/FK markers and UNQ for unconditional single-column unique constraints/indexes. Index details appear below each table in small, left-aligned text. Names stay intact; definitions wrap according to table width. Long names may widen a table. Full metadata remains in tooltips; `--hide-indexes` hides captions and `--force-appendix` also lists metadata in an appendix.

D2 reserves caption space before layout. After rendering, the tool aligns only each caption's x coordinate with its actual table, checking that it fits inside the reserved space. This handles engine padding and self loops without changing table or FK coordinates. Running D2 directly on the source skips this alignment. Captions use SVG `foreignObject`; view in a browser, since some image converters omit them. Regenerate existing SVGs to apply the fix; reverting the tool revision restores the previous caption format.

Regenerate existing diagrams to show index details. Indexed tables now have a containing D2 node, so scripts using generated object paths must account for the `_erd_table` child. Python callers can restore the previous structure with `show_indexes=False` in `build_d2()` and `render_optimized()`.

| Problem | What to check |
| --- | --- |
| SQL/schema/FK error | Inspect the marked `.partial` preview and `parse_log/` diagnostics; fix and rerun. Formal outputs are preserved; no preview is produced if no tables remain. |
| Layout configuration error | Fix the reported configuration before regenerating the formal diagram. |
| D2 missing or wrong version | Install exactly 0.7.1, check `d2 --version`, or set `--d2-binary`. |
| TALA unavailable | Put `d2plugin-tala` on PATH and check `d2 layout tala`; see [setup](#optional-tala-layout). |
| Rendering failure | The new D2 source is retained and the previous SVG is unchanged. Fix the error and rerun. |
| Timeout | Inspect diagram size and increase `--render-timeout` if needed. |

Exit codes: **0** success, **1** generation/rendering failure, **2** invalid options. Source and SVG replacement are separate operations, so automation must check the exit code. Processing runs locally; no SQL or diagram is uploaded.

## Additional CLI options

Common display options are in the README; `--help` lists all options.

| Option | Purpose |
| --- | --- |
| `--d2-binary PATH` | Rendering executable; defaults to `d2`. |
| `--render-timeout SECONDS` | Positive timeout per D2 process; default 120. At most 4 render passes with ELK or 3 with TALA. |
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

CI runs these checks on Python 3.11 and 3.14. Ruff checks imports, modern Python syntax, unused variables, common bugs and redundant constructs; formatting covers every Python file. Use `python -m ruff check . --fix` for safe fixes, then review the diff.

Fast tests do not require D2. Integration tests require exactly D2 0.7.1 with ELK and fail if it is unavailable. Optional TALA tests skip when `d2plugin-tala` is absent; once installed, run them with `python -m pytest -q -m tala`. A present but broken plugin fails those tests. Unit tests live beside their modules; CLI and rendering tests live under `tests/`. Use synthetic fixtures only; keep company SQL, local research and generated diagrams out of Git.

Cleanup removed the unused `Index.uses_expression()`, `iter_columns()` and `iter_foreign_keys()` helpers. Python integrations can read `Index.expression_columns`, `Table.columns` and `Table.foreign_keys` directly; reverting the cleanup commit restores the helpers.

### Code map

```text
SQL + optional FK YAML → Schema → D2 source → D2 (ELK or TALA) → SVG
```

| Responsibility | Modules |
| --- | --- |
| CLI and orchestration | [cli.py](erd_generator/cli.py) |
| SQL loading and diagnostics | [sql_parser.py](erd_generator/sql_parser.py), `migrations.py`, `sql_statements.py`, `postgres_commands.py`, `postgres_exclusions.py`, `postgres_do.py`, `diagnostics.py` |
| Schema, preview filtering and configuration | [schema.py](erd_generator/schema.py), `validation.py`, `fk_config.py`, `layout_config.py` |
| Pure layout and D2 generation | [d2.py](erd_generator/d2.py), `d2_affinity.py`, `d2_business.py`, `d2_grouping.py`, `d2_layout.py`, `d2_dimensions.py`, `d2_emit.py`, `d2_indexes.py`, `d2_references.py`, `d2_styles.py` |
| Rendering and layout comparison | [d2_renderer.py](erd_generator/d2_renderer.py), `d2_index_svg.py`, `d2_refinement.py`, `d2_geometry.py` |
| Engine choices and render flags | [d2_engines.py](erd_generator/d2_engines.py) |
| Atomic source publication | [artifacts.py](erd_generator/artifacts.py) |

CLI loads inputs and coordinates generation. Planners operate on Schema without I/O or mutation; the renderer does not depend on Schema or planners. `d2_refinement` coordinates rendering candidates and geometry checks. Lower-level modules must not import the coordinator or CLI.
