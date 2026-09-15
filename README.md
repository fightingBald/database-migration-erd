# Database ER Diagram Generator

Turn PostgreSQL migration SQL into ER diagrams with **D2 + ELK**. No database connection needed.

## Features

- Show tables, columns, data types, keys and relationships.
- Support composite foreign keys, self references and extra relationships supplied in YAML.
- Read dollar-quoted SQL, static `DO` blocks and common role/permission setup blocks.
- Pack independent tables and relationship groups into compact columns; export D2 or SVG.

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
python -m erd_generator ./db/migration ./generated/schema.svg
```

This reads the SQL files under `./db/migration` and creates `schema.svg` plus `schema.d2` in `./generated/`. Open the SVG in a browser. Replace the paths with your own; the input should include the migrations needed to build the schema.

To generate only D2 source, change the output extension. This does not require D2 to be installed:

```bash
python -m erd_generator ./db/migration ./generated/schema.d2
```

The default uses clean styling, compact placement and visible column types. Add options after the two paths when needed:

| Option | Purpose |
| --- | --- |
| `--fk-config file.yaml` | Add relationships; see the [sample YAML](sample_fk_config.yaml). |
| `--direction down` | Lay out related tables from top to bottom. |
| `--hide-types` | Hide column data types. |
| `--style classic` | Use the original visual style. |

Supports common PostgreSQL schema migrations. See the [developer guide](dev_guide.md) for supported SQL, all options, troubleshooting and development.
