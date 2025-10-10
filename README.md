# db_migraton_diagram_generator

Generate simple draw.io ERD diagrams directly from a directory of PostgreSQL-style migration SQL files.

## Features
- Parses `CREATE TABLE` (including inline/table-level PRIMARY KEY and FOREIGN KEY definitions) plus common `ALTER TABLE` statements (add/drop/alter columns, add/drop constraints, rename columns/tables/constraints).
- Normalises identifiers so cross-file foreign keys resolve reliably.
- Produces draw.io XML using the built-in `table` shape with PK markers, optional data types, and an index summary note beneath each table (highlighting unique/partial/expression indexes). Optionally emits a lightweight PNG snapshot for quick previews.
- Auto-layered layout groups related tables (following foreign-key levels) with generous spacing; tweak via `--per-row` if needed.

## Installation
No packaging step is required. Use the repository directly with Python 3.9+.

```bash
python3 --version
```

## Usage
```bash
python3 gen_drawio_erd_table.py \
  --migrations ./db/migration \
  --out ./schema.drawio \
  --out-png ./schema.png \
  --show-types \
  --per-row 0
```

Arguments:
- `--migrations`: root directory containing migration SQL files.
- `--out`: where the `.drawio` document will be written.
- `--out-png`: optional PNG snapshot rendered by the built-in rasteriser.
- `--show-types`: include column data types in the table rows.
- `--per-row`: optional layout tuning; tables per row (default `0` = automatic based on graph).

The generated `schema.drawio` can be opened with [diagrams.net](https://app.diagrams.net/) or draw.io desktop.

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
