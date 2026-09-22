# Database ER Diagram Generator

Turn PostgreSQL migration SQL into **SVG ER diagrams**, without a database connection. Uses **D2 + ELK**; **TALA** is optional.

[![Fictional library ER diagram with 16 tables in four automatic groups](https://github.com/fightingBald/database_migrate_UML_generator/releases/download/v0.1.0/dummy-library.png)](https://github.com/fightingBald/database_migrate_UML_generator/releases/download/v0.1.0/dummy-library.png)

Fictional library schema, generated with default settings. [Download the SVG](https://github.com/fightingBald/database_migrate_UML_generator/releases/download/v0.1.0/dummy-library.svg).

## Features

- Tables, columns, types, keys and index details below each table.
- Composite foreign keys, self references and additional relationships from YAML.
- Automatic grouping, colours and compact layouts.
- Forward PostgreSQL migrations, including supported dollar-quoted `DO` blocks.

## Install

Requires **Python 3.11+** and [D2 0.7.1](https://github.com/d2lang/d2/releases/tag/v0.7.1) on PATH.

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Usage

Pass the **migration directory** and **output SVG**:

```bash
python -m erd_generator ./migrations ./generated/schema.svg
```

Supply the migrations needed to build your schema. The command creates only `schema.svg`; open it in a browser. Grouping, colours and column types are enabled automatically.

Errors appear in the terminal; no log files are written by default. On SQL/schema errors, the command exits **1**, preserves the existing SVG and, when possible, writes an **INCOMPLETE** `schema.partial.svg` for diagnosis.

| Option | Purpose |
| --- | --- |
| `--fk-config file.yaml` | [Add relationships](dev_guide.md#relationships-without-database-fk-constraints). |
| `--layout-config file.yaml` | [Set groups, titles and colours](dev_guide.md#business-layout). |
| `--layout tala` | [Use TALA](dev_guide.md#optional-tala-layout). |
| `--show-references` | Label cross-group FK targets beside fields. |

Run `python -m erd_generator --help` for all options. See the [developer guide](dev_guide.md) to embed this tool under `tools/erd-generator/`, call it from codegen/CI, or work on the tool itself.
