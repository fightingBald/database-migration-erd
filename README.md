## Summary
- Generate draw.io ERDs directly from PostgreSQL-style migrations.
- Minimal, self-contained SQL parser (no DB connection required).
- Graph-aware layout and constraint annotations aid visual inspection.

# db_migraton_diagram_generator

Generate simple draw.io ERD diagrams directly from a directory of PostgreSQL-style migration SQL files.

## Features
- Parses `CREATE TABLE` (including inline/table-level PRIMARY KEY and FOREIGN KEY definitions) plus common `ALTER TABLE` statements (add/drop/alter columns, add/drop constraints, rename columns/tables/constraints).
- Normalises identifiers so cross-file foreign keys resolve reliably.
- Produces draw.io XML using the built-in `table` shape with PK markers, optional data types, and a constraint note beneath each table (primary key, foreign keys, indexes).
- Auto-layered layout groups related tables (following foreign-key levels) with generous spacing; tweak via `--per-row` if needed.
- Built on top of [sqlglot](https://github.com/tobymao/sqlglot) for robust PostgreSQL DDL parsing and [NetworkX](https://networkx.org/) for graph-aware layout ordering.

## Installation
Ensure Python 3.9+ is available; no packaging step is required.

## Environment Setup
```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Usage
```bash
python3 gen_drawio_erd_table.py \
  --migrations ./db/migration \
  --out ./schema.drawio \
  --show-types \
  --per-row 0
```

Arguments:
- `--migrations`: root directory containing migration SQL files.
- `--out`: where the `.drawio` document will be written.
- `--show-types`: include column data types in the table rows.
- `--per-row`: optional layout tuning; tables per row (default `0` = automatic based on graph).

The generated `schema.drawio` can be opened with [diagrams.net](https://app.diagrams.net/) or draw.io desktop.

## Repository Structure
- `gen_drawio_erd_table.py`: thin CLI shim that delegates to the library modules.
- `erd_generator/sql_parser.py`: extracts table/column/constraint metadata from PostgreSQL-style migrations.
- `erd_generator/schema.py`: shared data classes plus helpers for mutating schema state.
- `erd_generator/layout.py`: computes graph-aware table placement and note positioning.
- `erd_generator/drawio.py`: renders the collected schema into draw.io XML elements.
- `db/migration/`: sample migrations covering the supported DDL patterns.

## Supported SQL Snippets
The parser targets a practical subset of PostgreSQL DDL with predictable formatting. Currently handled constructs include:
- `CREATE TABLE` with inline / table-level `PRIMARY KEY`, `UNIQUE`, and `FOREIGN KEY` definitions.
- `ALTER TABLE` for `ADD/DROP COLUMN`, `ALTER COLUMN` type/nullability, `ADD/DROP/RENAME` constraints, and table/column renames.
- `CREATE [UNIQUE] INDEX` (supporting `USING` methods, simple expressions like `lower(email)`, and `WHERE` filters), plus `DROP INDEX` and `ALTER INDEX ... RENAME`.
- `DROP TABLE [IF EXISTS]` with cascading cleanup of referencing foreign keys/index metadata.

Unsupported-but-common features (handled as no-ops) include `SET/DROP DEFAULT`, `CHECK` constraints, partition syntax, and rewriting expression definitions during renames.

## Known Limitations
- Only a small SQL subset is supported (PostgreSQL DDL). Exotic syntax, quoted identifiers with spaces, and database-specific extensions may require manual adjustments.
- Inline multi-column foreign keys are mapped as one edge (using the first column), which is usually sufficient for ERD visualisation but does not capture all column pairings.
- Advanced ALTER patterns (e.g. ALTER COLUMN SET DEFAULT, CHECK constraints, expression indexes, function-based index column rewrites) are ignored; apply them manually if needed.
- Views, enums, and other object types are ignored.

## Development Notes
- Core code lives in the `erd_generator` package with clear separation between SQL parsing, layout, and draw.io rendering.
- Run `python3 gen_drawio_erd_table.py --help` to see the latest CLI options.
- Contributions: add migration fixtures under `db/migration` and regenerate `schema.drawio` to verify changes visually.
