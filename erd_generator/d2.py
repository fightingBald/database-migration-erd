"""Deterministic D2 SQL-table source generation. No I/O or layout dependencies."""

from .d2_styles import CLEAN_CONFIG, CLEAN_CONNECTION, CLEAN_TABLE, STYLES
from .schema import Schema, Table
from .validation import Relationship, primary_columns, validate_schema


def quote_d2(value: str) -> str:
    """Quote keys and values, including substitutions which JSON quoting permits."""
    if any(ord(c) < 32 and c not in "\t\r\n" for c in value):
        raise ValueError("D2 text contains an unsupported control character")
    value = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("${", "\\${")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{value}"'


def _unique_columns(table: Table) -> set[str]:
    unique = set()
    for index in table.indexes:
        names = index.column_names or index.columns
        if (
            not index.unique
            or index.where
            or index.expression_columns
            or len(names) != 1
        ):
            continue
        if names[0] is None:
            continue
        matches = [c.name for c in table.columns if c.name == names[0]]
        if not matches:
            matches = [
                c.name for c in table.columns if c.name.lower() == names[0].lower()
            ]
        if len(matches) == 1:
            unique.add(matches[0])
    return unique


def _notes(table: Table, relations: tuple[Relationship, ...]) -> str:
    lines = []
    primary = primary_columns(table)
    if primary:
        lines.append(
            f"{table.primary_key_name or 'PK'}: ({', '.join(sorted(primary))})"
        )
    for fk in relations:
        if fk.table == table.name:
            lines.append(
                f"{fk.name or 'FK'}: ({', '.join(fk.columns)}) -> {fk.ref_table} ({', '.join(fk.ref_columns)})"
            )
    for index in sorted(
        table.indexes,
        key=lambda i: (
            i.name or "",
            i.columns,
            i.unique,
            i.method or "",
            i.where or "",
        ),
    ):
        label = "Unique index" if index.unique else "Index"
        name = f" {index.name}" if index.name else ""
        method = f" using {index.method}" if index.method else ""
        where = f" where {index.where}" if index.where else ""
        lines.append(f"{label}{name}{method} on [{', '.join(index.columns)}]{where}")
    return "\n".join(lines)


def build_d2(
    schema: Schema,
    *,
    show_types: bool = False,
    direction: str = "right",
    style: str = "clean",
) -> str:
    if direction not in {"up", "down", "left", "right"}:
        raise ValueError("D2 direction must be up, down, left or right")
    if style not in STYLES:
        raise ValueError("D2 style must be clean or classic")
    result = validate_schema(schema)
    if result.errors:
        raise ValueError("Schema validation failed: " + "; ".join(result.errors))
    lines = [
        "# Generated from migrations; edit SQL or FK configuration, then regenerate.",
        "vars: {",
        "  d2-config: {",
        "    layout-engine: elk",
        *(CLEAN_CONFIG if style == "clean" else ()),
        "  }",
        "}",
        f"direction: {direction}",
        "",
    ]
    foreign_columns: dict[str, set[str]] = {}
    for fk in result.relationships:
        foreign_columns.setdefault(fk.table, set()).update(fk.columns)
    for name, table in sorted(schema.items()):
        lines.extend([f"{quote_d2(name)}: {{", "  shape: sql_table"])
        if style == "clean":
            lines.extend(CLEAN_TABLE)
        primary = primary_columns(table)
        foreign = foreign_columns.get(name, set())
        unique = _unique_columns(table)
        for column in table.columns:
            constraints = [
                label
                for label, names in (
                    ("primary_key", primary),
                    ("foreign_key", foreign),
                    ("unique", unique),
                )
                if column.name in names
            ]
            suffix = ""
            if constraints:
                value = (
                    constraints[0]
                    if len(constraints) == 1
                    else f"[{'; '.join(constraints)}]"
                )
                suffix = f" {{constraint: {value}}}"
            data_type = column.data_type if show_types else ""
            lines.append(f"  {quote_d2(column.name)}: {quote_d2(data_type)}{suffix}")
        notes = _notes(table, result.relationships)
        if notes:
            lines.append(f"  tooltip: {quote_d2(notes)}")
        lines.extend(["}", ""])
    for fk in result.relationships:
        count = len(fk.columns)
        for number, (local, remote) in enumerate(zip(fk.columns, fk.ref_columns), 1):
            connection = f"{quote_d2(fk.table)}.{quote_d2(local)} -> {quote_d2(fk.ref_table)}.{quote_d2(remote)}"
            edge_label = ""
            if count > 1:
                label = fk.name or f"FK ({', '.join(fk.columns)})"
                edge_label = f"{label} [{number}/{count}]"
            if fk.table == fk.ref_table:
                # D2 0.7.1/ELK routes self loops around the table boundary; retain
                # visible field semantics even when row ports are not respected.
                edge_label = (
                    f"{edge_label}: " if edge_label else ""
                ) + f"{local} → {remote}"
            if edge_label:
                connection += f": {quote_d2(edge_label)}"
            if style == "clean":
                lines.extend(
                    [
                        connection + (" {" if edge_label else ": {"),
                        *CLEAN_CONNECTION,
                        "}",
                    ]
                )
            else:
                lines.append(connection)
    return "\n".join(lines).rstrip() + "\n"
