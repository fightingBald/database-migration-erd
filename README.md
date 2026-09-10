# db_migraton_diagram_generator

Generate ER diagrams from PostgreSQL migration SQL **without a database connection**.
The primary workflow produces D2 source and renders SVG with D2's bundled ELK layout:

```text
SQL migrations + optional FK YAML → Schema → schema.d2 → D2 / ELK → schema.svg
```

The draw.io exporter, relationship extractor, comparator and existing Python APIs remain available through explicit compatibility commands.

## Quick start

Use Python **3.11+** and **D2 0.7.1**. Local validation used Python 3.14; CI is configured for 3.11 and 3.14. Rendering checks the exact D2 version to keep layout behavior reproducible.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt

# Install D2 0.7.1 from its official release, then verify it:
d2 --version
d2 layout elk

# Generate generated/schema.d2 and generated/schema.svg from the sample migrations:
make run
```

Download D2 from the [official 0.7.1 release](https://github.com/d2lang/d2/releases/tag/v0.7.1). ELK is included; no separate ELK service is needed. `requirements.txt` installs runtime dependencies; `requirements-dev.txt` also installs pytest and Ruff. The original dependency installation surface still includes NetworkX/pydot for draw.io compatibility, but the D2 path does not import them.

Open `generated/schema.svg` in a browser. Only producing `.d2` source requires no D2 executable:

```bash
make gen
```

## Generate your diagram

```bash
.venv/bin/python -m erd_generator \
  --migrations ./db/migration \
  --out ./generated/schema.d2 \
  --show-types \
  --fk-config sample_fk_config.yaml \
  --render svg
```

Omit `--render svg` to generate source only. The image always uses the same directory and filename stem as the `.d2` source. Generated files are overwritten by regeneration; edit migrations, FK configuration or generation options rather than the generated files.

Make accepts equivalent overrides:

```bash
make run MIGRATIONS=/path/to/migrations SOURCE=generated/project.d2 FK_CONFIG=/path/to/fks.yaml
make gen MIGRATIONS=/path/to/migrations FK_CONFIG=
```

| Option | Behavior |
| --- | --- |
| `--migrations PATH` | Required migration directory; scans SQL recursively |
| `--out PATH` | Required `.d2` source output; `.drawio`/`.xml` for the legacy backend |
| `--format d2\|drawio` | Module entrypoint defaults to `d2` |
| `--show-types` | Display SQL column types; otherwise retain names and constraints |
| `--fk-config PATH` | Add relationships declared in YAML |
| `--layout elk` | D2 always uses ELK; draw.io accepts `grid` or `graphviz` |
| `--direction right\|left\|up\|down` | Global D2 direction, default `right` |
| `--render svg` | Render source with the pinned D2 CLI |
| `--d2-binary PATH` | Rendering executable, default `d2`; requires `--render` |
| `--render-timeout SECONDS` | Positive timeout per D2 process, default 120; requires `--render` |
| `--force-appendix` | Display tooltip contents in the SVG appendix; requires `--render` |
| `--log-dir PATH` | Write detected SQL/configuration diagnostics to `PATH/parse_log/`; default working directory |

The main command logs table, column and foreign-key counts, rendering version/layout and duration. Invalid options return exit code 2; generation/rendering errors return 1; complete requested output returns 0.

## Table and relationship behavior

- Each table is a D2 `sql_table`; fully qualified names are quoted as one key.
- Primary and foreign-key columns receive PK/FK markers, including both on the same column.
- Single-column, unconditional unique constraints/indexes receive UNQ markers. Composite, partial and expression indexes remain in the notes without incorrectly marking individual columns unique.
- Foreign-key arrows point from referencing columns to referenced columns. Explicit composite keys create one connector per column pair, labeled with a common constraint and pair number.
- Repeated FK declarations are deduplicated. Columns retain their Schema order; table, relationship and note ordering is deterministic.
- Primary keys, complete foreign keys and indexes (including available names, methods and predicates) appear in table tooltips. `--force-appendix` makes the notes visible without hovering.
- Self references have explicit `source_column → target_column` labels: D2 0.7.1/ELK may route self loops to table boundaries rather than exact row ports. The project renderer sets `--elk-nodeSelfLoop=100` to leave room for these labels.

This replaces draw.io's fixed note blocks beneath each table with tooltips/appendices. D2 handles text quoting, including reserved keywords, dots, quotes, backslashes, Unicode and literal `${...}` sequences.

See [D2 SQL tables](https://d2lang.com/tour/sql-tables/) and [ELK](https://d2lang.com/tour/elk/) for the upstream rendering model.

## Relationships without database FK constraints

Three sources are supported:

1. Native inline or table-level `FOREIGN KEY` definitions.
2. Column comments such as `-- FK public.users(id)`.
3. Additional YAML relationships supplied through `--fk-config`.

```yaml
users:
  fks:
    - [role_id, roles, id]
    - [manager_id, users, id]

order_items:
  fks:
    - [order_id, purchase_orders, id]
    - [product_id, products, id]
```

Each triple is `[local_column, target_table, target_column]`. Composite relationships use `[[tenant_id, user_id], memberships, [tenant_id, id]]`. The historical two-item YAML shorthand `[id, target_table]` means the same column name on both sides.

In the D2 path, a short table name must resolve unambiguously. Wrong qualified names, unknown columns and malformed entries fail generation; use explicit qualified names when schemas share table names. YAML adds relationships and does not replace conflicting SQL declarations.

SQL `REFERENCES table` without column names is supported when the target has a single primary-key column. Omitted composite references fail clearly because the existing Schema stores primary keys as an unordered set; it cannot safely infer the declaration order. Explicit composite reference columns are supported.

## Migration loading and errors

Versioned files named `V<number>__description.sql` are ordered numerically, including dot/underscore version components; `V2` precedes `V10`. Non-versioned filenames follow versioned files in path order. This is a file ordering contract, not a complete Flyway migration-history implementation. Keep version names unique and include the complete migration history.

The loader reads UTF-8 strictly. The D2 workflow stops on detected SQL/configuration failures or invalid relationships before overwriting source output. Diagnostics include file/object context and omit SQL/YAML payloads from generator console/file logs.

Rendering explicitly requests ELK and ignores ambient `D2_*`/`ELK_*` environment configuration. It has no fallback to another backend or layout. SVG is rendered to a temporary file and verified before replacing the target. If rendering fails, the generated `.d2` is retained, the previous SVG is unchanged, and the command reports that the SVG was not updated. Source and SVG replacement are separate operations; automation must check the exit code.

No SQL or diagram is uploaded to an online service by these commands.

## Complex scenarios for demonstrations

```bash
make demo
make demo DEMO=release_evolution
```

Open `generated/demos/index.html` for four fictional business diagrams and six expected-failure demonstrations, with D2 sources, exact commands, logs and a JSON report. The scenarios exercise multi-tenant composite relationships, schema evolution, cross-system YAML/comment relationships, and Unicode/long labels with an appendix. `DEMO` also accepts `tenant_orders`, `logical_relationships` and `readability`; the default `all` includes the failure demonstrations.

The automated checks validate structure, rendering and artifact preservation. Browser inspection found overlapping labels in the dense composite self-reference case; the gallery explicitly marks this layout limitation. See the [scenario guide and presentation walkthrough](examples/README.md) for commands, expected outcomes and visual limits. Each example directory is an independent input; do not pass the whole `examples/` tree as one migration history.

## draw.io compatibility and rollback

The existing command retains draw.io as its default:

```bash
.venv/bin/python gen_drawio_erd_table.py \
  --migrations ./db/migration \
  --out ./generated/schema.drawio \
  --show-types --layout grid \
  --fk-config sample_fk_config.yaml
```

The new command can also select it explicitly:

```bash
.venv/bin/python -m erd_generator --format drawio \
  --migrations ./db/migration --out ./generated/schema.drawio
```

`--per-row`, `--graphviz-prog`, `--graphviz-scale` and `--graphviz-spacing` apply only to draw.io. Graphviz requires a system `dot` binary and a working NetworkX Graphviz adapter. Its historical fallback to grid is retained; it does not apply to D2.

Existing tools remain usable:

```bash
.venv/bin/python parse_drawio_edges.py generated/schema.drawio > recovered_fks.yaml
.venv/bin/python compare_drawio_to_migrations.py db/migration generated/schema.drawio --out schema_diff.txt
```

The extractor reports unmapped endpoints and writes a companion anomaly log. The comparator reports differences in tables, columns, FK notes and index notes; `--debug` prints additional parsed metadata. It compares native migrations without YAML additions, so YAML-only relationships are expected differences. It is a legacy report command, not a D2 validator or a nonzero-exit CI difference gate.

Rollback of the default workflow consists of explicitly invoking the old command and using its `.drawio` output. Existing `erd_generator.main()`, `build_parser()` and `build_drawio()` retain their default backend/API behavior. Parser correctness fixes apply to both backends. No database migration or deployment rollback is needed.

## Repository structure

```text
erd_generator/
  __main__.py          # primary python -m entrypoint (D2 default)
  cli.py               # common argument validation and orchestration
  schema.py            # output-independent schema contract
  sql_parser.py        # SQL adapters and per-run loading result
  diagnostics.py       # shared diagnostics (ParseFailure remains re-exported)
  fk_config.py         # YAML relationship loading/resolution
  validation.py        # FK integrity checks and normalized relationships
  d2.py                # pure deterministic D2 source generation
  d2_renderer.py       # pinned D2/ELK execution and SVG publication
  drawio.py            # retained draw.io exporter
  layout.py            # draw.io-only grid/Graphviz placement
  drawio_parser.py     # retained XML reader
  schema_diff.py       # retained draw.io comparison
  test_*.py            # unit tests close to implementation
tests/
  test_cli.py          # subprocess CLI and import-boundary tests
  test_legacy_tools.py # extraction/comparison compatibility
  integration/        # real pinned D2 rendering; missing D2 is a failure
  fixtures/           # explicit small SQL/D2 expectations
scripts/              # synthetic rendering benchmark and CLI demo/gallery runner
examples/             # fictional business inputs, expected failures and scenario catalog
db/migration/         # sample SQL migrations
sample_fk_config.yaml # sample additional relationships
generated/            # ignored generated source, SVG and benchmark output
.github/workflows/    # build/test/lint and real ELK checks
docs/                 # migration design and local validation record
```

The new explicit loading API is `erd_generator.sql_parser.load_schema_result(path)` returning this run's Schema and diagnostics. The old `load_schema_from_migrations()` / `get_last_parse_failures()` functions remain available for callers using the historical last-run cache. D2 source generation is available as `erd_generator.build_d2(schema, show_types=True)` and never mutates its input.

## Development and validation

```bash
make build && make test
make lint
make test-integration
make run
make demo
make benchmark
```

`make test` runs fast tests without requiring D2. `make test-integration` requires exactly D2 0.7.1 and bundled ELK; missing dependencies fail rather than skip rendering validation. `make format` formats new/rewritten modules while preserving formatting of untouched legacy files. Override `PYTHON=python` when using an already activated environment.

`make benchmark` separately renders deterministic 50- and 200-table synthetic inputs. Each case writes source, SVG and `metrics.json` under `generated/benchmark-N/`, including duration, peak child-process RSS, output bytes and dimensions. These measurements do not predict every production graph's readability or runtime.

CI installs the fixed D2 release with an SHA-256 check and runs build, tests, lint, real rendering and the default command. [Migration design](docs/plans/d2-elk-migration.md) describes boundaries and rollback stages; [local validation](docs/validation/d2-elk.md) records measured results and remaining limits.

## Supported SQL and limitations

The parser supports a practical PostgreSQL DDL subset: CREATE TABLE, common ALTER column/constraint/rename operations, DROP TABLE/COLUMN/CONSTRAINT/INDEX, CREATE INDEX (including expression/partial metadata) and ALTER INDEX RENAME. The pinned sqlglot DROP representation is handled explicitly, so removed objects no longer remain in the diagram.

The sample plus YAML has **5 tables, 21 columns, 5 FKs and 7 unique/index records** after all migrations. Both the original inline email UNIQUE and the later explicitly named email UNIQUE remain represented.

CHECK/default changes, partitioning, views, enums, stored procedures, search_path resolution and all exotic DDL are not fully modeled. Some are ignored by the existing parser and some yield diagnostics; zero diagnostics do not prove complete PostgreSQL interpretation. Quoted identifier normalization and index-expression rewrites retain existing parser limitations.

ELK uses hierarchical layout. Dense/large diagrams may contain crossings, extra bends or become wide; there is no automatic business-domain splitting or fixed-coordinate placement. SVG is intended for browser viewing. PNG/PDF and their browser dependencies are outside the first release.
