# Developer guide

CLI reference, schema behavior, compatibility tools and contributor workflows. For installation and everyday use, see the [README](README.md).

## Environment

Use Python **3.11+** and **D2 0.7.1**. Local validation used Python 3.14; CI is configured for 3.11 and 3.14. Rendering checks the exact D2 version to keep layout behavior reproducible; both `0.7.1` and `v0.7.1` version strings are accepted.

Download D2 from the [official 0.7.1 release](https://github.com/d2lang/d2/releases/tag/v0.7.1). ELK is included; no separate ELK service is needed. `requirements.txt` installs runtime dependencies; `requirements-dev.txt` also installs pytest and Ruff. The original dependency installation surface still includes NetworkX/pydot for draw.io compatibility, but the D2 path does not import them.

## CLI reference

```bash
python -m erd_generator SQL_DIR OUTPUT
```

Both paths are required. `SQL_DIR` is the migration directory. The output extension selects what to generate:

| Output | Files written | D2 executable required? |
| --- | --- | --- |
| `./generated/schema.svg` | `schema.svg` and `schema.d2` in `./generated/` | Yes |
| `./generated/schema.d2` | `schema.d2` only | No |

The short command defaults to ELK, clean styling, rightward layout and visible column types. Additional FK YAML is loaded only when explicitly supplied. No example relationships or input/output paths are selected implicitly.

Optional overrides follow the two paths:

```bash
python -m erd_generator ./db/migration ./generated/schema.svg --fk-config ./sample_fk_config.yaml
python -m erd_generator ./db/migration ./generated/schema.svg --direction down
python -m erd_generator ./db/migration ./generated/schema.d2 --hide-types
```

Quote paths containing spaces. Generated files are overwritten by regeneration; edit migrations, FK configuration or generation options rather than the generated files.

| Option | Behavior |
| --- | --- |
| `--style clean\|classic` | D2 visual preset, default `clean`; `classic` restores the original appearance |
| `--hide-types` | Hide SQL column types; retain names and constraints |
| `--show-types` | Explicitly display SQL column types; already enabled for the short command |
| `--fk-config PATH` | Add relationships declared in YAML |
| `--layout elk` | D2 always uses ELK; normally omitted |
| `--direction right\|left\|up\|down` | Global D2 direction, default `right` |
| `--d2-binary PATH` | Rendering executable, default `d2`; requires SVG output |
| `--render-timeout SECONDS` | Positive timeout per D2 process, default 120; requires SVG output |
| `--force-appendix` | Display tooltip contents in the SVG appendix; requires SVG output |
| `--log-dir PATH` | Write detected SQL/configuration diagnostics to `PATH/parse_log/`; default working directory |

The main command logs table, column and foreign-key counts, rendering version/layout and duration. Invalid options return exit code 2; generation/rendering errors return 1; complete requested output returns 0.

Existing named commands remain supported, including `--render svg` with a `.d2` output:

```bash
python -m erd_generator --migrations ./db/migration --out ./generated/schema.d2 --show-types --render svg
```

Use either the two positional paths or `--migrations` plus `--out`; mixing them is rejected. Named commands retain their previous defaults: column types are hidden unless `--show-types` is supplied, and a `.d2` output does not render unless `--render svg` is supplied. Named `--out` also accepts `.svg`. To roll back to the previous invocation style, keep using the named command; existing scripts and Makefile targets continue to work. The positional form is for D2; explicit draw.io commands are documented below.

## Table and relationship behavior

- The default `clean` style uses blue-grey headers, white table bodies, light separators, dark field names, muted types, teal constraint markers and rounded slate-coloured connections. Connection labels use regular text. The palette and styles are embedded in the D2 source.
- Each table is a D2 `sql_table`; fully qualified names are quoted as one key.
- Primary and foreign-key columns receive PK/FK markers, including both on the same column.
- Single-column, unconditional unique constraints/indexes receive UNQ markers. Composite, partial and expression indexes remain in the notes without incorrectly marking individual columns unique.
- Foreign-key arrows point from referencing columns to referenced columns. Explicit composite keys create one connector per column pair, labeled with a common constraint and pair number.
- Repeated FK declarations are deduplicated. Columns retain their Schema order; table, relationship and note ordering is deterministic.
- Primary keys, complete foreign keys and indexes (including available names, methods and predicates) appear in table tooltips. `--force-appendix` makes the notes visible without hovering.
- Self references have explicit `source_column → target_column` labels: D2 0.7.1/ELK may route self loops to table boundaries rather than exact row ports. The project renderer sets `--elk-nodeSelfLoop=100` to leave room for these labels.

This replaces draw.io's fixed note blocks beneath each table with tooltips/appendices. D2 handles text quoting, including reserved keywords, dots, quotes, backslashes, Unicode and literal `${...}` sequences.

See [D2 SQL tables](https://d2lang.com/tour/sql-tables/) and [ELK](https://d2lang.com/tour/elk/) for the upstream rendering model.

Use `--style classic` to restore the original D2 appearance. Both presets preserve the same column definitions, constraints and relationship endpoints. `--style` applies only to D2. The implementation uses [native D2 styles](https://d2lang.com/tour/style/) and [theme overrides](https://d2lang.com/tour/themes/).

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

## PostgreSQL blocks and setup statements

Statement splitting uses the pinned sqlglot PostgreSQL tokenizer. It preserves `$$...$$` and `$tag$...$tag$` literals, quoted strings/identifiers and nested block comments, so their internal semicolons do not split statements. Tags are case-sensitive. Unterminated tokens produce a sanitized diagnostic with the input file and statement line.

| Input | ERD behavior |
| --- | --- |
| `GRANT`, `REVOKE`, `ALTER DEFAULT PRIVILEGES` | Skip permission changes. |
| `CREATE ROLE`, `CREATE USER` | Skip account creation; credentials are not logged. |
| Standalone `CREATE SCHEMA`, including `IF NOT EXISTS` and `AUTHORIZATION` | Skip the namespace declaration. |
| `CREATE FUNCTION` / `CREATE PROCEDURE` with ordinary string or dollar-quoted bodies | Skip the definition; never apply its body as if the routine had been called. |
| Dollar-quoted, straight-line PL/pgSQL `DO ... BEGIN ... END` | Apply the existing supported table/index DDL subset in order. Permission/setup commands, `NULL` and literal-only `RAISE NOTICE`/`INFO`/`DEBUG`/`LOG`/`WARNING` statements are skipped. |
| Conditional or dynamic blocks, declarations, nested blocks, exception handlers, calls or expression evaluation | Report unsupported input; do not assume which schema changes occur. |
| `CREATE SCHEMA` containing object definitions, `ALTER SCHEMA`, `DROP SCHEMA` | Report unsupported input; these can change diagram objects. |

For example, this static block is supported:

```sql
CREATE SCHEMA app;
DO $migration$
BEGIN
    CREATE TABLE app.items (id integer PRIMARY KEY);
    ALTER TABLE app.items ADD COLUMN label text;
END;
$migration$;
```

The optional `LANGUAGE plpgsql` clause may appear before or after the dollar-quoted body. This is static schema extraction, not a PL/pgSQL interpreter or a database execution check. `IF`, loops, `EXECUTE`, `CALL`, `PERFORM`, variable declarations and nested `DO` blocks remain unsupported. Unqualified names retain the parser's existing `search_path` limitations; use qualified names when schema identity matters.

Each supported `DO` block is applied to a temporary Schema copy. If any statement in the block fails, none of its changes reach the caller's Schema. The loader can still collect later statements for diagnostics, but any error prevents D2/SVG output from being replaced. Use ordinary DDL or a reviewed schema snapshot for migrations whose structural effects require runtime evaluation; there is no option to silently ignore unknown blocks.

The allowlist classifies structural impact and does not validate every PostgreSQL permission or role option. Skipped command categories and static block completion are logged at DEBUG without SQL payloads. No additional dependencies, CLI flags or database connection are required. Reverting this parser change restores the previous parsing behavior; no database rollback is involved.

## Migration loading and errors

Versioned files named `V<number>__description.sql` are ordered numerically, including dot/underscore version components; `V2` precedes `V10`. Non-versioned filenames follow versioned files in path order. This is a file ordering contract, not a complete Flyway migration-history implementation. Keep version names unique and include the complete migration history.

The loader reads UTF-8 strictly. The D2 workflow stops on detected SQL/configuration failures or invalid relationships before overwriting source output. Diagnostics include file/object context and omit SQL/YAML payloads from generator console/file logs.

Rendering explicitly requests ELK and ignores ambient `D2_*`/`ELK_*` environment configuration. It has no fallback to another backend or layout. SVG is rendered to a temporary file and verified before replacing the target. If rendering fails, the generated `.d2` is retained, the previous SVG is unchanged, and the command reports that the SVG was not updated. Source and SVG replacement are separate operations; automation must check the exit code.

No SQL or diagram is uploaded to an online service by these commands.

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
SQL migrations + optional FK YAML → Schema → schema.d2 → D2 / ELK → schema.svg
```

```text
README.md             # user setup and everyday usage
dev_guide.md          # CLI reference, architecture and contributor workflows
erd_generator/
  __main__.py          # primary python -m entrypoint (D2 default)
  cli.py               # explicit input/output CLI, argument validation and orchestration
  schema.py            # output-independent schema contract
  sql_parser.py        # SQL adapters and per-run loading result
  sql_statements.py    # PostgreSQL tokenization and statement boundaries
  postgres_commands.py # ERD-neutral allowlist and bounded DO block extraction
  diagnostics.py       # shared diagnostics (ParseFailure remains re-exported)
  fk_config.py         # YAML relationship loading/resolution
  validation.py        # FK integrity checks and normalized relationships
  d2.py                # pure deterministic D2 source generation
  d2_styles.py         # native D2 palette, table and connection presets
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
scripts/              # reproducible synthetic rendering benchmark
db/migration/         # sample SQL migrations
sample_fk_config.yaml # sample additional relationships
generated/            # ignored generated source, SVG and benchmark output
.github/workflows/    # build/test/lint and real ELK checks
docs/                 # migration design and local validation record
```

The new explicit loading API is `erd_generator.sql_parser.load_schema_result(path)` returning this run's Schema and diagnostics. The old `load_schema_from_migrations()` / `get_last_parse_failures()` functions remain available for callers using the historical last-run cache. D2 source generation is available as `erd_generator.build_d2(schema, show_types=True, style="clean")` and never mutates its input; `style="classic"` preserves the original D2 output style.

## Development and validation

```bash
python -m pip install -r requirements-dev.txt
python -m compileall -q erd_generator scripts gen_drawio_erd_table.py parse_drawio_edges.py compare_drawio_to_migrations.py
python -m pytest -q -m 'not integration'
python -m ruff check .
python -m ruff format --check .
python -m pytest -q -m integration
python -m erd_generator ./db/migration ./generated/schema.svg
python scripts/benchmark_rendering.py --tables 50
python scripts/benchmark_rendering.py --tables 200
```

The `not integration` marker runs fast tests without requiring D2. The `integration` marker requires exactly D2 0.7.1 and bundled ELK; missing dependencies fail rather than skip rendering validation. `python -m ruff format .` formats new/rewritten modules while preserving formatting of untouched legacy files.

The benchmark script separately renders deterministic 50- and 200-table synthetic inputs. Each case writes source, SVG and `metrics.json` under `generated/benchmark-N/`, including duration, peak child-process RSS, output bytes and dimensions. These measurements do not predict every production graph's readability or runtime.

CI installs the fixed D2 release with an SHA-256 check and runs build, tests, lint, real rendering and the default command. [Migration design](docs/plans/d2-elk-migration.md) describes boundaries and rollback stages; [local validation](docs/validation/d2-elk.md) records measured results and remaining limits.

## Supported SQL and limitations

The parser supports a practical PostgreSQL DDL subset: CREATE TABLE, common ALTER column/constraint/rename operations, DROP TABLE/COLUMN/CONSTRAINT/INDEX, CREATE INDEX (including expression/partial metadata) and ALTER INDEX RENAME. The pinned sqlglot DROP representation is handled explicitly, so removed objects no longer remain in the diagram.

The sample plus YAML has **5 tables, 21 columns, 5 FKs and 7 unique/index records** after all migrations. Both the original inline email UNIQUE and the later explicitly named email UNIQUE remain represented.

CHECK/default changes, partitioning, views, enums, routine execution, search_path resolution and all exotic DDL are not fully modeled. Routine definitions and supported setup statements are ignored as described above; unsupported procedural execution and schema mutations yield diagnostics. Some other constructs are still ignored by the existing parser, so zero diagnostics do not prove complete PostgreSQL interpretation. Quoted identifier normalization and index-expression rewrites retain existing parser limitations.

ELK uses hierarchical layout. Dense/large diagrams may contain crossings, extra bends or become wide; there is no automatic business-domain splitting or fixed-coordinate placement. SVG is intended for browser viewing. PNG/PDF and their browser dependencies are outside the first release.
