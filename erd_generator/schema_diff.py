"""Helpers to diff migration-derived schemas against draw.io documents."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from .drawio_parser import DiagramTable, parse_drawio_tables
from .schema import Schema, Table
from .sql_parser import load_schema_from_migrations


def _normalize_identifier(value: str) -> str:
    return value.strip().lower()


@dataclass(frozen=True)
class ForeignKeySummary:
    local_columns: Tuple[str, ...]
    ref_table: str
    ref_columns: Tuple[str, ...]


@dataclass(frozen=True)
class IndexSummary:
    columns: Tuple[str, ...]
    unique: bool
    where: str = ""


@dataclass
class TableSummary:
    name: str
    columns: Set[str] = field(default_factory=set)
    foreign_keys: Set[ForeignKeySummary] = field(default_factory=set)
    indexes: Set[IndexSummary] = field(default_factory=set)


@dataclass
class SchemaSnapshot:
    tables: Dict[str, TableSummary]


def _table_columns(table: Table) -> Set[str]:
    return {_normalize_identifier(column.name) for column in table.columns}


def _table_foreign_keys(table: Table) -> Set[ForeignKeySummary]:
    summaries: Set[ForeignKeySummary] = set()
    for fk in table.foreign_keys:
        local = tuple(_normalize_identifier(col) for col in fk.columns)
        ref_table = _normalize_identifier(fk.ref_table)
        ref_columns = tuple(_normalize_identifier(col) for col in fk.ref_columns)
        summaries.add(
            ForeignKeySummary(
                local_columns=local,
                ref_table=ref_table,
                ref_columns=ref_columns,
            )
        )
    return summaries


def _table_indexes(table: Table) -> Set[IndexSummary]:
    summaries: Set[IndexSummary] = set()
    for idx in table.indexes:
        column_names: Sequence[str]
        if idx.column_names:
            column_names = [col or "" for col in idx.column_names]
        else:
            column_names = [col for col in idx.columns]
        normalized_columns = tuple(_normalize_identifier(col) for col in column_names if col)
        where_clause = (idx.where or "").strip().lower()
        summaries.add(
            IndexSummary(
                columns=normalized_columns,
                unique=idx.unique,
                where=where_clause,
            )
        )
    return summaries


def snapshot_from_schema(schema: Schema) -> SchemaSnapshot:
    tables: Dict[str, TableSummary] = {}
    for table_name, table in schema.items():
        normalized = _normalize_identifier(table_name)
        tables[normalized] = TableSummary(
            name=table_name,
            columns=_table_columns(table),
            foreign_keys=_table_foreign_keys(table),
            indexes=_table_indexes(table),
        )
    return SchemaSnapshot(tables=tables)


def _parse_fk_note(line: str) -> ForeignKeySummary | None:
    stripped = line.strip()
    if not stripped.upper().startswith("FK "):
        return None
    payload = stripped[3:].strip()
    if "->" not in payload:
        return None
    local_part, target_part = payload.split("->", 1)
    local_columns = tuple(
        _normalize_identifier(chunk)
        for chunk in local_part.split(",")
        if chunk.strip()
    )
    target_part = target_part.strip()
    ref_columns: Tuple[str, ...]
    if "." in target_part:
        table_part, column_part = target_part.split(".", 1)
        ref_table = _normalize_identifier(table_part)
        ref_columns = tuple(
            _normalize_identifier(chunk)
            for chunk in column_part.split(",")
            if chunk.strip()
        )
    else:
        ref_table = _normalize_identifier(target_part)
        ref_columns = tuple()
    return ForeignKeySummary(local_columns=local_columns, ref_table=ref_table, ref_columns=ref_columns)


def _parse_index_note(line: str) -> IndexSummary | None:
    stripped = line.strip()
    lowered = stripped.lower()
    if "index on [" not in lowered:
        return None
    unique = lowered.startswith("unique ")
    if unique:
        stripped = stripped[len("Unique ") :]
        lowered = stripped.lower()
    if not lowered.startswith("index on ["):
        return None
    remainder = stripped[len("Index on [") :]
    if "]" not in remainder:
        return None
    columns_part, tail = remainder.split("]", 1)
    columns = tuple(
        _normalize_identifier(chunk)
        for chunk in columns_part.split(",")
        if chunk.strip()
    )
    where_clause = ""
    tail = tail.strip()
    if tail.lower().startswith("where "):
        where_clause = tail[6:].strip().lower()
    return IndexSummary(columns=columns, unique=unique, where=where_clause)


def _table_columns_from_diagram(table: DiagramTable) -> Set[str]:
    return {_normalize_identifier(column) for column in table.columns if column}


def _table_foreign_keys_from_diagram(table: DiagramTable) -> Set[ForeignKeySummary]:
    summaries: Set[ForeignKeySummary] = set()
    for line in table.note_lines:
        summary = _parse_fk_note(line)
        if summary:
            summaries.add(summary)
    return summaries


def _table_indexes_from_diagram(table: DiagramTable) -> Set[IndexSummary]:
    summaries: Set[IndexSummary] = set()
    for line in table.note_lines:
        summary = _parse_index_note(line)
        if summary:
            summaries.add(summary)
    return summaries


def snapshot_from_drawio(path: str) -> SchemaSnapshot:
    diagram_tables = parse_drawio_tables(path)
    tables: Dict[str, TableSummary] = {}
    for table in diagram_tables.values():
        normalized = _normalize_identifier(table.name)
        tables[normalized] = TableSummary(
            name=table.name,
            columns=_table_columns_from_diagram(table),
            foreign_keys=_table_foreign_keys_from_diagram(table),
            indexes=_table_indexes_from_diagram(table),
        )
    return SchemaSnapshot(tables=tables)


def _format_column_list(columns: Iterable[str]) -> str:
    ordered = sorted(columns)
    return ", ".join(ordered)


def _format_fk(table_name: str, summary: ForeignKeySummary) -> str:
    local = _format_column_list(summary.local_columns) or "<none>"
    ref_columns = _format_column_list(summary.ref_columns)
    target = summary.ref_table or "<unknown>"
    ref_part = f"{target}.{ref_columns}" if ref_columns else target
    return f"{table_name}: ({local}) -> {ref_part}"


def _format_index(table_name: str, summary: IndexSummary) -> str:
    prefix = "Unique " if summary.unique else ""
    cols = _format_column_list(summary.columns) or "<none>"
    text = f"{table_name}: {prefix}index on [{cols}]"
    if summary.where:
        text += f" where {summary.where}"
    return text


def generate_diff_report(migration_snapshot: SchemaSnapshot, drawio_snapshot: SchemaSnapshot) -> str:
    lines: List[str] = []
    migration_tables = migration_snapshot.tables
    drawio_tables = drawio_snapshot.tables
    migration_keys = set(migration_tables)
    drawio_keys = set(drawio_tables)

    def section(title: str, items: List[str]) -> None:
        lines.append(title)
        if not items:
            lines.append("  (none)")
        else:
            for item in items:
                lines.append(f"  - {item}")
        lines.append("")

    only_migrations = sorted(migration_keys - drawio_keys)
    only_drawio = sorted(drawio_keys - migration_keys)
    section("Tables only in migrations", [migration_tables[key].name for key in only_migrations])
    section("Tables only in draw.io", [drawio_tables[key].name for key in only_drawio])

    missing_columns: List[str] = []
    extra_columns: List[str] = []
    for key in sorted(migration_keys & drawio_keys):
        mig_table = migration_tables[key]
        dia_table = drawio_tables[key]
        missing = sorted(mig_table.columns - dia_table.columns)
        extra = sorted(dia_table.columns - mig_table.columns)
        if missing:
            missing_columns.append(f"{mig_table.name}: {', '.join(missing)}")
        if extra:
            extra_columns.append(f"{mig_table.name}: {', '.join(extra)}")
    section("Columns missing in draw.io", missing_columns)
    section("Columns only in draw.io", extra_columns)

    missing_fks: List[str] = []
    extra_fks: List[str] = []
    for key in sorted(migration_keys & drawio_keys):
        mig_table = migration_tables[key]
        dia_table = drawio_tables[key]
        missing = mig_table.foreign_keys - dia_table.foreign_keys
        extra = dia_table.foreign_keys - mig_table.foreign_keys
        if missing:
            missing_fks.extend(
                _format_fk(mig_table.name, fk)
                for fk in sorted(missing, key=lambda item: (item.ref_table, item.local_columns))
            )
        if extra:
            extra_fks.extend(
                _format_fk(dia_table.name, fk)
                for fk in sorted(extra, key=lambda item: (item.ref_table, item.local_columns))
            )
    section("Foreign keys missing in draw.io", missing_fks)
    section("Foreign keys only in draw.io", extra_fks)

    missing_indexes: List[str] = []
    extra_indexes: List[str] = []
    for key in sorted(migration_keys & drawio_keys):
        mig_table = migration_tables[key]
        dia_table = drawio_tables[key]
        missing = mig_table.indexes - dia_table.indexes
        extra = dia_table.indexes - mig_table.indexes
        if missing:
            missing_indexes.extend(
                _format_index(mig_table.name, idx)
                for idx in sorted(missing, key=lambda item: (item.columns, item.unique, item.where))
            )
        if extra:
            extra_indexes.extend(
                _format_index(dia_table.name, idx)
                for idx in sorted(extra, key=lambda item: (item.columns, item.unique, item.where))
            )
    section("Indexes missing in draw.io", missing_indexes)
    section("Indexes only in draw.io", extra_indexes)

    return "\n".join(lines).rstrip() + "\n"


def run_diff_cli(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare migration SQL schemas with a draw.io diagram.")
    parser.add_argument("migrations", help="Path to the root of migration SQL files")
    parser.add_argument("drawio", help="Path to the draw.io (.drawio) file to compare")
    parser.add_argument("--out", help="Optional path to write the diff report (defaults to stdout)")
    args = parser.parse_args(argv)

    migration_schema = load_schema_from_migrations(args.migrations)
    migration_snapshot = snapshot_from_schema(migration_schema)
    drawio_snapshot = snapshot_from_drawio(args.drawio)
    report = generate_diff_report(migration_snapshot, drawio_snapshot)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(report)
    else:
        print(report, end="")
    return 0


__all__ = [
    "SchemaSnapshot",
    "snapshot_from_schema",
    "snapshot_from_drawio",
    "generate_diff_report",
    "run_diff_cli",
]
