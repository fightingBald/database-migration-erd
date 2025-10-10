# db_migraton_diagram_generator

Generate simple draw.io ERD diagrams directly from a directory of PostgreSQL-style migration SQL files.

## Features
- Parses `CREATE TABLE` (including inline/table-level PRIMARY KEY and FOREIGN KEY definitions) plus common `ALTER TABLE` statements (add/drop/alter columns, add/drop constraints, rename columns/tables/constraints).
- Normalises identifiers so cross-file foreign keys resolve reliably.
- Produces draw.io XML using the built-in `table` shape with PK markers and optional data types.
- Automatic grid layout that respects varying table heights to avoid overlapping rows.

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
  --show-types \
  --per-row 3
```

Arguments:
- `--migrations`: root directory containing migration SQL files.
- `--out`: where the `.drawio` document will be written.
- `--show-types`: include column data types in the table rows.
- `--per-row`: optional layout tuning; number of tables rendered per row (default `3`).

The generated `schema.drawio` can be opened with [diagrams.net](https://app.diagrams.net/) or draw.io desktop.

## Known Limitations
- Only a small SQL subset is supported (PostgreSQL DDL). Exotic syntax, quoted identifiers with spaces, and database-specific extensions may require manual adjustments.
- Inline multi-column foreign keys are mapped as one edge (using the first column), which is usually sufficient for ERD visualisation but does not capture all column pairings.
- Advanced ALTER patterns (e.g. ALTER COLUMN SET DEFAULT, CHECK constraints, expression indexes) are ignored; apply them manually if needed.
- Views, enums, and other object types are ignored.

## Development Notes
- Core code lives in the `erd_generator` package with clear separation between SQL parsing, layout, and draw.io rendering.
- Run `python3 gen_drawio_erd_table.py --help` to see the latest CLI options.
- Contributions: add migration fixtures under `db/migration` and regenerate `schema.drawio` to verify changes visually.
