# Database ER Diagram Generator

Turn PostgreSQL migration SQL into ER diagrams with **D2 + ELK**. No database connection needed.

Outputs are `.d2` source and `.svg` images. D2 + ELK is the only backend.

[![Fictional library ER diagram with 16 tables in four automatic groups](https://github.com/fightingBald/database_migrate_UML_generator/releases/download/v0.1.0/dummy-library.png)](https://github.com/fightingBald/database_migrate_UML_generator/releases/download/v0.1.0/dummy-library.png)

Entirely fictional library schema, generated with default settings. Click to enlarge or [download the SVG](https://github.com/fightingBald/database_migrate_UML_generator/releases/download/v0.1.0/dummy-library.svg).

## Features

- Show tables, columns, data types, keys and relationships, with index details below each table.
- Support composite foreign keys, self references and extra relationships supplied in YAML.
- Read dollar-quoted SQL, static `DO` blocks and common role/permission setup blocks.
- Read forward migrations: sql-migrate/goose Up sections and `.up.sql` files; skip rollback SQL.
- Skip views, routine definitions, top-level procedure calls and extension setup; reject indexes targeting unknown tables.
- Infer business groups with matching colours and automatically compare layouts for spacious diagrams, keeping a more compact result when quality improves.

## Install

Requires **Python 3.11+**. To generate SVG images, install [D2 0.7.1](https://github.com/d2lang/d2/releases/tag/v0.7.1) and make sure `d2` is on your PATH.

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Usage

Pass your **SQL directory** followed by the **output file**:

```bash
python -m erd_generator ./migrations ./generated/schema.svg
```

Replace `./migrations` with your SQL directory. The command creates `schema.svg` plus `schema.d2` in `./generated/`. Open the SVG in a browser. Supply the migrations needed to build your schema.

On SQL/schema errors, the command returns **1** and preserves the normal outputs. When possible, it writes `schema.partial.d2` and `schema.partial.svg` with a visible **INCOMPLETE** notice; details are in `parse_log/`. Fix the errors and rerun before publishing.

To generate only D2 source, change the output extension. This does not require D2 to be installed:

```bash
python -m erd_generator ./migrations ./generated/schema.d2
```

The default uses clean styling, automatic business grouping, compact placement and visible column types. No grouping configuration is required. Add options after the two paths when needed:

| Option | Purpose |
| --- | --- |
| `--fk-config file.yaml` | Add relationships; see the [YAML format](dev_guide.md#relationships-without-database-fk-constraints). |
| `--layout-config file.yaml` | Override group membership, titles or colours; see [business layout](dev_guide.md#business-layout). |
| `--show-references` | Show cross-group target tables and keys beside FK fields, e.g. `FK → books.id`; makes tables wider. |
| `--direction down` | Lay out related tables from top to bottom. |
| `--grouping none` | Disable automatic grouping and hub placement. |
| `--hide-types` | Hide column data types. |
| `--hide-indexes` | Hide index details below tables; retain tooltip notes. |
| `--style classic` | Use the original visual style. |

Supports common PostgreSQL schema migrations. See the [developer guide](dev_guide.md) for supported SQL, all options, troubleshooting and development.

To regenerate diagrams in CI and display them in Docusaurus, see [CI integration](dev_guide.md#ci-and-docusaurus).

To include the tool under `tools/erd-generator/` in an existing project, see [codegen integration](dev_guide.md#use-inside-an-existing-project).
