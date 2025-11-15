# db_migraton_diagram_generator
* Generate draw.io ERD diagrams directly from `YOUR_MIGRATION_FOLDER_FILEPATH` **(no DB connection required)**.
* This project is aim to help the LAZY-ASS save the time to manually draw the ERD diagrams when you have a set of migration files.
* The generated diagram could be DRAG and DROP directly in browser https://www.drawio.com/

## Features
- Parses `CREATE TABLE` (including inline/table-level PRIMARY KEY and FOREIGN KEY definitions) plus common `ALTER TABLE` statements (add/drop/alter columns, add/drop constraints, rename columns/tables/constraints).
- Normalises identifiers so cross-file foreign keys resolve reliably.
- Produces draw.io XML using the built-in `table` shape with PK markers, optional data types, and a constraint note beneath each table (primary key, foreign keys, indexes).
- Auto-layered layout groups related tables (following foreign-key levels) with generous spacing; tweak via `--per-row` if needed.
- Optional Graphviz-powered layout (`--layout graphviz`) reduces overlap by delegating positioning to Graphviz (falls back to the grid layout if the dependency is missing).
- Built on top of [sqlglot](https://github.com/tobymao/sqlglot) for robust PostgreSQL DDL parsing and [NetworkX](https://networkx.org/) for graph-aware layout ordering.
- Emits per-run warnings for unsupported SQL (e.g. dialect gaps) and can archive them as timestamped files for later inspection.
- Understands inline foreign key hints written as comments (e.g. `-- FK public.users(id)`), which is handy when referential integrity lives in the application layer.
- Draws foreign key connectors between the actual columns involved instead of generic table-to-table arrows for clearer attribute lineage.

## Installation
Ensure Python 3.9+ is available; no packaging step is required.

## Environment Setup
```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```
> Graphviz layout mode requires the `graphviz` system package plus either PyGraphviz or pydot (the latter is listed in `requirements.txt`). If the `dot` binary is missing, the CLI falls back to the default grid layout automatically.

## Usage Example In This Repository (with sample migrations and files)
You could use this example generated `schema.drawio` from the sample migrations in `./db/migration` and includes foreign key hints from `sample_fk_config.yaml`, to see what it gives and check the result(drag and drop the generated `./schema.drawio` ) in the drawIO website 

**REPLACE THE PATHS AS NEEDED**:
```bash
python3 gen_drawio_erd_table.py \
  --migrations ./db/migration \
  --out ./schema.drawio \
  --show-types \
  --per-row 0 \
  --layout grid \
  --log-dir . \
  --fk-config sample_fk_config.yaml
```
Switch to Graphviz layout (with extra spacing) like so:
```bash
python3 gen_drawio_erd_table.py \
  --migrations ./db/migration \
  --out ./schema.drawio \
  --show-types \
  --layout graphviz \
  --graphviz-scale 1.5 \
  --graphviz-spacing 300 \
  --fk-config sample_fk_config.yaml
```
The default Graphviz engine is `dot`. Use `--graphviz-prog neato` (or any other Graphviz binary) to experiment with different layouts, and `--graphviz-spacing` to add extra padding between nodes when needed.
> Graphviz handles node placement automatically, but densely connected or very large diagrams can still produce overlaps. Adjust `--graphviz-scale`, pick a different program via `--graphviz-prog`, or fall back to `--layout grid --per-row ...`; worst case, tidy things manually inside draw.io.

Arguments:
- `--migrations`: root directory containing migration SQL files.
- `--out`: where the `.drawio` document will be written.
- `--show-types`: include column data types in the table rows.
- `--per-row`: optional layout tuning; tables per row (default `0` = automatic based on graph).
- `--log-dir`: optional base directory for parse logs; the tool writes to `<log-dir>/parse_log/parse_failures_<timestamp>.log` (default root: current working directory).
- `--fk-config`: optional YAML file providing extra foreign-key relationships to inject before rendering.

### Foreign key relation support when in DB level there's no foreign keys explicitly defined

When database-level foreign keys are omitted, there are three ways to keep relationships intact:

- **Native DDL**: declared `FOREIGN KEY` constraints in your migration SQL are parsed automatically.
- **Comment hints**: annotate the referencing column with a line comment in the form `-- FK schema.table(column[, ...])`. The parser is whitespace-tolerant, so formats like `-- FK  public.products ( id )` are accepted.
- **YAML overrides**: supply an external map of relationships for legacy databases or application-managed integrity.

### Foreign key configuration via YAML

Sometimes migrations omit foreign keys entirely. Supply a YAML file via `--fk-config` to stitch tables together explicitly:

```yaml
users:
  fks:
    - [role_id, roles, id]
    - [manager_id, users, id]
```

Each entry is `[local_column, target_table, target_column]`. Multi-column relationships can be expressed with nested lists (e.g. `[[tenant_id, user_id], memberships, [tenant_id, id]]`). The loader logs to the same parse log output when the YAML file cannot be parsed.

The YAML is handled by the dedicated `erd_generator.fk_config` module, keeping CLI wiring slim and making it easy to unit-test override scenarios.

Example assets for quick testing are included:
- `db/migration/V6__roles_and_managers.sql` adds `role_id` and `manager_id` columns without database constraints.
- `sample_fk_config.yaml` links those columns (and a couple of earlier tables) so you can run `python3 gen_drawio_erd_table.py ... --fk-config sample_fk_config.yaml` and confirm the overrides appear in the diagram.

The generated `schema.drawio` can be opened with [diagrams.net](https://app.diagrams.net/) or draw.io desktop.

## Repository Structure
- `gen_drawio_erd_table.py`: thin CLI shim that delegates to the library modules.
- `erd_generator/sql_parser.py`: extracts table/column/constraint metadata from PostgreSQL-style migrations.
- `erd_generator/schema.py`: shared data classes plus helpers for mutating schema state.
- `erd_generator/layout.py`: computes graph-aware table placement and note positioning.
- `erd_generator/drawio.py`: renders the collected schema into draw.io XML elements.
- `erd_generator/drawio_parser.py`: walks existing draw.io XML and resolves table/column nodes plus edges.
- `erd_generator/fk_config.py`: loads foreign-key relationship overrides from YAML files.
- `parse_drawio_edges.py`: CLI wrapper that emits FK-config-style YAML plus anomaly logs.
- `db/migration/`: sample migrations covering the supported DDL patterns.

## Extract relationships from existing draw.io files
When you already have a `.drawio` document and only want the table/column connection list, run:

```bash
python3 parse_drawio_edges.py path/to/schema.drawio > sample_fk_config.yaml
```

The parser:
- picks table cells via `vertex="1"` + `shape=table;` styles and uses their `value` as the table name.
- looks through descendant row/column cells to recover column names (skipping helper labels such as `PK`/`FK`, and falling back to empty strings when none can be resolved).
- ignores annotation/text nodes (style starting with `text;`) so notes like unique index descriptions do not pollute the output.
- walks every connector (`edge="1"`) so even visually-connected-but-unmapped edges show up in the log; missing pieces are rendered as placeholders such as `__MISSING_START_TABLE_12__` so you can fill them in later.
- emits FK-config-style YAML compatible with `erd_generator.fk_config`, grouping foreign keys by source table (every edge is included, even when placeholders are needed).
- prints warnings/informational logs for missing tables/columns and writes a companion text report (`<diagram>.edge_anomalies.log`, override with `--failure-log`) enumerating the problematic edges for manual cleanup.

## Compare draw.io diagrams with migrations
Need to verify that the diagram stays in sync with the migrations? Run the comparator CLI:

```bash
python3 compare_drawio_to_migrations.py ./db/migration ./schema.drawio --out schema_diff.txt
```

The generated text report highlights:
- tables that exist only in migrations or only in the diagram
- missing/extra columns per shared table
- foreign keys present in one source but not the other (based on the FK note block under each table)
- index differences derived from the same note block

## Supported SQL Snippets
The parser targets a practical subset of PostgreSQL DDL with predictable formatting. Currently handled constructs include:
- `CREATE TABLE` with inline / table-level `PRIMARY KEY`, `UNIQUE`, and `FOREIGN KEY` definitions.
- Foreign-key hints embedded in column comments using `-- FK <target_table>(<target_column>)`.
- `ALTER TABLE` for `ADD/DROP COLUMN`, `ALTER COLUMN` type/nullability, `ADD/DROP/RENAME` constraints, and table/column renames.
- `CREATE [UNIQUE] INDEX` (supporting `USING` methods, simple expressions like `lower(email)`, and `WHERE` filters), plus `DROP INDEX` and `ALTER INDEX ... RENAME`.
- `DROP TABLE [IF EXISTS]` with cascading cleanup of referencing foreign keys/index metadata.

Unsupported-but-common features (handled as no-ops) include `SET/DROP DEFAULT`, `CHECK` constraints, partition syntax, and rewriting expression definitions during renames.

## Known Limitations
- Only a small SQL subset is supported (PostgreSQL DDL). Exotic syntax, quoted identifiers with spaces, and database-specific extensions may require manual adjustments.
- Multi-column foreign keys draw one connector per column pair when both sides are provided; if the SQL omits or mismatches reference columns we fall back to a single edge.
- Advanced ALTER patterns (e.g. ALTER COLUMN SET DEFAULT, CHECK constraints, expression indexes, function-based index column rewrites) are ignored; apply them manually if needed.
- Views, enums, and other object types are ignored.

## Development Notes
- Run `python3 gen_drawio_erd_table.py --help` to see the latest CLI options.
- Contributions: add migration fixtures under `db/migration` and regenerate `schema.drawio` to verify changes visually.
