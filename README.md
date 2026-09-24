# Database Migration ERD

**Readable ER diagrams from database migration SQL. No database connection required.**

[![64 fictional tables automatically arranged into six groups](https://github.com/fightingBald/database-migration-erd/releases/download/v0.2.0/layout-after.png)](https://github.com/fightingBald/database-migration-erd/releases/download/v0.2.0/layout-after.svg)

64 dummy tables, six automatically inferred groups, default settings. [Before/after and tool comparison](https://fightingbald.github.io/database-migration-erd/) · [Download SVG](https://github.com/fightingBald/database-migration-erd/releases/download/v0.2.0/layout-after.svg)

## Why use it?

- **Layout for larger schemas:** automatic groups and colours, measured cluster packing, and cross-group FK routing. Built on D2 + ELK; optional TALA.
- **Useful table detail:** column types, composite keys, self references and index descriptions below tables. Add missing relationships with YAML.
- **Migration-aware input:** forward SQL changes, sql-migrate/goose Up sections and supported dollar-quoted `DO` blocks, processed locally without executing SQL.
- **Fits codegen and CI:** one command, SVG-only output by default, meaningful exit codes and previous SVG preserved on failure.

**SQL support:** the parser currently uses the PostgreSQL dialect. Compatible SQL from other databases may work, but full MySQL, SQLite and SQL Server migration support is not verified. It reads SQL files, not ORM migration code, and never applies migrations. See [supported SQL and limitations](https://github.com/fightingBald/database-migration-erd/blob/main/dev_guide.md#sql-support-and-diagnostics).

## Install

Requires **Python 3.11+**, [pipx](https://pipx.pypa.io/stable/installation/) and [D2 0.7.1](https://github.com/d2lang/d2/releases/tag/v0.7.1) on PATH. Install the versioned package from GitHub Releases:

```bash
pipx install https://github.com/fightingBald/database-migration-erd/releases/download/v0.2.1/migration_erd-0.2.1-py3-none-any.whl
```

## Usage

Pass the **migration directory** and **output SVG**:

```bash
migration-erd ./migrations ./generated/schema.svg
```

Supply the complete migration history. The command creates only `schema.svg`; open it in a browser. Grouping, colours and column types are enabled by default.

Errors appear in the terminal, with a nonzero exit code and the previous SVG preserved. No log files are written by default.

| Option | Purpose |
| --- | --- |
| `--fk-config file.yaml` | [Add relationships](https://github.com/fightingBald/database-migration-erd/blob/main/dev_guide.md#relationships-without-database-fk-constraints). |
| `--layout-config file.yaml` | [Set groups, titles and colours](https://github.com/fightingBald/database-migration-erd/blob/main/dev_guide.md#business-layout). |
| `--layout tala` | [Use TALA](https://github.com/fightingBald/database-migration-erd/blob/main/dev_guide.md#optional-tala-layout). |
| `--show-references` | Label cross-group FK targets beside fields. |

Run `migration-erd --help` for all options. The [developer guide](https://github.com/fightingBald/database-migration-erd/blob/main/dev_guide.md) covers source installation, copying into `tools/erd-generator/`, CI and development. `python -m erd_generator` remains available.

Found a parsing or layout problem? [Report it with a small fictional SQL example](https://github.com/fightingBald/database-migration-erd/issues/new?template=bug_report.yml).
