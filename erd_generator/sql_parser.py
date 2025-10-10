"""SQL parsing helpers backed by sqlglot."""
from __future__ import annotations

import glob
import os
import re
from typing import List, Optional, Sequence, Tuple

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from .schema import (
    Column,
    ForeignKey,
    Index,
    Schema,
    Table,
    rename_column_in_schema,
    rename_table,
)

RENAME_CONSTRAINT_RE = re.compile(
    r"""
    ^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?P<table>"[^"]+"|\S+)\s+
    RENAME\s+CONSTRAINT\s+(?P<old>"[^"]+"|\S+)\s+TO\s+(?P<new>"[^"]+"|\S+)\s*;?\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


# ---------------------------------------------------------------------------
# Normalisation helpers


def _normalize_identifier(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    parts = []
    for chunk in text.split("."):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith('"') and chunk.endswith('"'):
            parts.append(chunk[1:-1])
        else:
            parts.append(chunk.lower())
    return ".".join(parts)


def _identifier_name(node: exp.Expression | str | None) -> str:
    if node is None:
        return ""
    if isinstance(node, exp.Identifier):
        value = node.this or ""
        quoted = bool(node.args.get("quoted"))
        return value if quoted else value.lower()
    if isinstance(node, exp.Table):
        parts = []
        if node.catalog:
            parts.append(_identifier_name(node.catalog))
        if node.db:
            parts.append(_identifier_name(node.db))
        parts.append(_identifier_name(node.this))
        return ".".join(part for part in parts if part)
    if isinstance(node, exp.Schema):
        return _identifier_name(node.this)
    if isinstance(node, exp.Column):
        return _identifier_name(node.this)
    if isinstance(node, exp.Var):
        return _identifier_name(node.this)
    if isinstance(node, exp.Literal):
        literal = node.this or ""
        return literal.lower() if not node.args.get("is_string") else literal
    if isinstance(node, str):
        return _normalize_identifier(node)
    return _normalize_identifier(node.sql(dialect="postgres"))


def _table_name(node: exp.Expression | str | None) -> str:
    name = _identifier_name(node)
    return name


def _column_name(node: exp.Expression | str | None) -> str:
    return _identifier_name(node)


def _expression_sql(node: Optional[exp.Expression]) -> str:
    if node is None:
        return ""
    return node.sql(dialect="postgres")


# ---------------------------------------------------------------------------
# Index formatting helpers


def _format_index_expression(expression: exp.Expression) -> Tuple[str, Optional[str]]:
    if isinstance(expression, exp.Column):
        column = _column_name(expression.this)
        return column.upper(), column
    if isinstance(expression, exp.Identifier):
        column = _identifier_name(expression)
        return column.upper(), column
    display = expression.sql(dialect="postgres")
    return display, None


def _format_ordered_expression(ordered: exp.Expression) -> Tuple[str, Optional[str]]:
    if isinstance(ordered, exp.Ordered):
        display, normalized = _format_index_expression(ordered.this)
        if ordered.args.get("desc"):
            display = f"{display} DESC"
        if ordered.args.get("nulls_first"):
            display = f"{display} NULLS FIRST"
        return display, normalized
    return _format_index_expression(ordered)


# ---------------------------------------------------------------------------
# Constraint ingestion


def _apply_primary_key(table: Table, pk_expr: exp.PrimaryKey, constraint_name: Optional[str]) -> None:
    columns: List[str] = []
    for item in pk_expr.expressions or []:
        if isinstance(item, exp.Ordered):
            target = item.this
        else:
            target = item
        columns.append(_column_name(target))
    table.set_primary_key(columns, constraint_name)


def _apply_foreign_key(table: Table, fk_expr: exp.ForeignKey, constraint_name: Optional[str]) -> None:
    local_columns = tuple(_column_name(col) for col in fk_expr.expressions or [])
    ref_table = ""
    ref_columns: Tuple[str, ...] = ()
    reference = fk_expr.args.get("reference")
    if isinstance(reference, exp.Reference):
        schema_expr = reference.this
        if isinstance(schema_expr, exp.Schema):
            ref_table = _table_name(schema_expr.this)
            ref_columns = tuple(_column_name(col) for col in schema_expr.expressions or [])
        else:
            ref_table = _table_name(schema_expr)
            ref_columns = tuple(_column_name(col) for col in reference.expressions or [])
    table.add_foreign_key(
        ForeignKey(columns=local_columns, ref_table=ref_table, ref_columns=ref_columns),
        constraint_name=constraint_name,
    )


def _apply_unique_constraint(table: Table, unique_expr: exp.UniqueColumnConstraint, constraint_name: Optional[str]) -> None:
    if isinstance(unique_expr.this, exp.Schema):
        column_expressions = unique_expr.this.expressions or []
    else:
        column_expressions = unique_expr.expressions or []
    displays: List[str] = []
    column_names: List[Optional[str]] = []
    expression_columns: List[str] = []
    for item in column_expressions or []:
        display, normalized = _format_index_expression(item)
        displays.append(display)
        column_names.append(normalized)
        if normalized is None:
            expression_columns.append(display)
    table.add_index(
        Index(
            name=constraint_name,
            columns=tuple(displays),
            column_names=tuple(column_names),
            expression_columns=tuple(expression_columns),
            unique=True,
        ),
        constraint_name=constraint_name,
        constraint_type="unique",
    )


def _apply_constraint(table: Table, constraint: exp.Constraint) -> None:
    constraint_name = _identifier_name(constraint.this)
    for item in constraint.expressions or []:
        if isinstance(item, exp.PrimaryKey):
            _apply_primary_key(table, item, constraint_name)
        elif isinstance(item, exp.ForeignKey):
            _apply_foreign_key(table, item, constraint_name)
        elif isinstance(item, exp.UniqueColumnConstraint):
            _apply_unique_constraint(table, item, constraint_name)


def _apply_column_constraints(table: Table, column: Column, constraints: Sequence[exp.ColumnConstraint]) -> None:
    pk_constraint_name: Optional[str] = None
    for constraint in constraints:
        constraint_name = _identifier_name(constraint.this)
        kind = constraint.args.get("kind")
        if isinstance(kind, exp.PrimaryKeyColumnConstraint):
            column.is_primary_key = True
            if constraint_name:
                pk_constraint_name = constraint_name
        elif isinstance(kind, exp.NotNullColumnConstraint):
            column.nullable = False
        elif isinstance(kind, exp.UniqueColumnConstraint):
            display = column.name.upper()
            table.add_index(
                Index(
                    name=constraint_name,
                    columns=(display,),
                    column_names=(column.name,),
                    expression_columns=tuple(),
                    unique=True,
                ),
                constraint_name=constraint_name,
                constraint_type="unique",
            )
        elif isinstance(kind, exp.Reference):
            schema_expr = kind.this
            ref_columns: Tuple[str, ...] = ()
            ref_table = ""
            if isinstance(schema_expr, exp.Schema):
                ref_table = _table_name(schema_expr.this)
                ref_columns = tuple(_column_name(col) for col in schema_expr.expressions or [])
            elif schema_expr is not None:
                ref_table = _table_name(schema_expr)
            table.add_foreign_key(
                ForeignKey(
                    columns=(column.name,),
                    ref_table=ref_table,
                    ref_columns=ref_columns,
                ),
                constraint_name=constraint_name,
            )
    if column.is_primary_key and pk_constraint_name:
        table.set_primary_key(table.primary_key, pk_constraint_name)


def _ingest_column_definition(table: Table, column_def: exp.ColumnDef) -> None:
    column = Column(name=_column_name(column_def.this))
    data_type = column_def.args.get("kind")
    column.data_type = _expression_sql(data_type)
    column.nullable = True
    column.is_primary_key = False
    constraints = column_def.args.get("constraints") or []
    _apply_column_constraints(table, column, constraints)
    table.add_column(column)


def _ingest_table_element(table: Table, element: exp.Expression) -> None:
    if isinstance(element, exp.ColumnDef):
        _ingest_column_definition(table, element)
    elif isinstance(element, exp.Constraint):
        _apply_constraint(table, element)
    elif isinstance(element, exp.PrimaryKey):
        _apply_primary_key(table, element, None)
    elif isinstance(element, exp.ForeignKey):
        _apply_foreign_key(table, element, None)
    elif isinstance(element, exp.UniqueColumnConstraint):
        _apply_unique_constraint(table, element, None)


# ---------------------------------------------------------------------------
# Statement handlers


def _handle_create_table(statement: exp.Create, schema: Schema) -> None:
    schema_expr = statement.this
    if not isinstance(schema_expr, exp.Schema):
        return

    table_name = _table_name(schema_expr.this)
    table = schema.setdefault(table_name, Table(name=table_name))
    table.columns.clear()
    table.primary_key.clear()
    table.foreign_keys.clear()
    table.indexes.clear()
    table.constraint_types.clear()
    table.primary_key_name = None

    for element in schema_expr.expressions or []:
        _ingest_table_element(table, element)
    table.sync_primary_key_flags()


def _handle_create_index(statement: exp.Create, schema: Schema) -> None:
    index_expr = statement.this
    if not isinstance(index_expr, exp.Index):
        return

    table_name = _table_name(index_expr.args.get("table"))
    table = schema.setdefault(table_name, Table(name=table_name))

    params = index_expr.args.get("params")
    column_items = params.args.get("columns") if isinstance(params, exp.IndexParameters) else None
    columns: List[str] = []
    column_names: List[Optional[str]] = []
    expression_columns: List[str] = []
    if column_items:
        for item in column_items:
            display, normalized = _format_ordered_expression(item)
            columns.append(display)
            column_names.append(normalized)
            if normalized is None:
                expression_columns.append(display)
    method = None
    where_clause = None
    if isinstance(params, exp.IndexParameters):
        using_expr = params.args.get("using")
        if isinstance(using_expr, exp.Var):
            method = _identifier_name(using_expr.this).upper()
        where_expr = params.args.get("where")
        if isinstance(where_expr, exp.Where):
            where_clause = _expression_sql(where_expr.this)

    index_name = _identifier_name(index_expr.this)
    index = Index(
        name=index_name or None,
        columns=tuple(columns),
        column_names=tuple(column_names),
        expression_columns=tuple(expression_columns),
        unique=bool(statement.args.get("unique")),
        method=method,
        where=where_clause,
    )
    table.add_index(index)


def _handle_create(statement: exp.Create, schema: Schema) -> None:
    kind = (statement.args.get("kind") or "").upper()
    if kind == "TABLE":
        _handle_create_table(statement, schema)
    elif kind == "INDEX":
        _handle_create_index(statement, schema)


def _handle_drop_table(table_name: str, schema: Schema) -> None:
    if table_name not in schema:
        return
    schema.pop(table_name, None)
    for table in schema.values():
        removed = [fk for fk in table.foreign_keys if fk.ref_table == table_name]
        if not removed:
            continue
        table.foreign_keys = [fk for fk in table.foreign_keys if fk.ref_table != table_name]
        for fk in removed:
            if fk.name:
                table.constraint_types.pop(fk.name.lower(), None)


def _handle_drop(statement: exp.Drop, schema: Schema) -> None:
    kind = (statement.args.get("kind") or "").upper()
    if kind == "TABLE":
        _handle_drop_table(_table_name(statement.this), schema)
    elif kind == "INDEX":
        target_name = _table_name(statement.this)
        for table in schema.values():
            if table.drop_index(target_name):
                break


def _handle_alter_table(statement: exp.Alter, schema: Schema) -> None:
    table_name = _table_name(statement.this)
    table = schema.setdefault(table_name, Table(name=table_name))
    current_table_name = table_name
    current_table = table

    for action in statement.args.get("actions") or []:
        if isinstance(action, exp.ColumnDef):
            _ingest_column_definition(current_table, action)
        elif isinstance(action, exp.AlterColumn):
            column_name = _column_name(action.this)
            if action.args.get("dtype"):
                current_table.update_data_type(column_name, _expression_sql(action.args["dtype"]))
            if "allow_null" in action.args:
                allow_null = action.args["allow_null"]
                current_table.update_nullable(column_name, bool(allow_null))
        elif isinstance(action, exp.AddConstraint):
            for expr in action.args.get("expressions") or []:
                if isinstance(expr, exp.Constraint):
                    _apply_constraint(current_table, expr)
                elif isinstance(expr, exp.PrimaryKey):
                    _apply_primary_key(current_table, expr, None)
                elif isinstance(expr, exp.ForeignKey):
                    _apply_foreign_key(current_table, expr, None)
                elif isinstance(expr, exp.UniqueColumnConstraint):
                    _apply_unique_constraint(current_table, expr, None)
        elif isinstance(action, exp.Drop):
            kind = (action.args.get("kind") or "").upper()
            if kind == "COLUMN":
                column_name = _column_name(action.this)
                current_table.drop_column(column_name)
            elif kind == "CONSTRAINT":
                constraint_name = _table_name(action.this)
                if constraint_name:
                    current_table.drop_constraint(constraint_name)
        elif isinstance(action, exp.RenameColumn):
            old_name = _column_name(action.this)
            new_name = _column_name(action.args.get("to"))
            if old_name and new_name and old_name != new_name:
                rename_column_in_schema(schema, current_table_name, old_name, new_name)
                current_table = schema[current_table_name]
        elif isinstance(action, exp.AlterRename):
            new_table_name = _table_name(action.this)
            if new_table_name and "." not in new_table_name and "." in current_table_name:
                prefix = current_table_name.rsplit(".", 1)[0]
                new_table_name = f"{prefix}.{new_table_name}"
            if new_table_name and new_table_name != current_table_name:
                rename_table(schema, current_table_name, new_table_name)
                current_table_name = new_table_name
                current_table = schema[current_table_name]

    current_table.sync_primary_key_flags()


def _handle_alter_index(statement: exp.Alter, schema: Schema) -> None:
    index_name = _table_name(statement.this)
    current_name = index_name
    for action in statement.args.get("actions") or []:
        if isinstance(action, exp.AlterRename):
            new_name = _table_name(action.this)
            if not new_name or new_name == current_name:
                continue
            for table in schema.values():
                if table.rename_index(current_name, new_name):
                    current_name = new_name
                    break


def _handle_alter(statement: exp.Alter, schema: Schema) -> None:
    kind = (statement.args.get("kind") or "").upper()
    if kind == "INDEX":
        _handle_alter_index(statement, schema)
    else:
        _handle_alter_table(statement, schema)


def _handle_command(command: exp.Command, schema: Schema) -> None:
    sql_text = command.sql(dialect="postgres")
    match = RENAME_CONSTRAINT_RE.match(sql_text)
    if not match:
        return
    table_name = _normalize_identifier(match.group("table"))
    old_name = _normalize_identifier(match.group("old"))
    new_name = _normalize_identifier(match.group("new"))
    table = schema.setdefault(table_name, Table(name=table_name))
    table.rename_constraint(old_name, new_name)


# ---------------------------------------------------------------------------
# Public API


def parse_schema_from_sql(sql: str, schema: Schema) -> None:
    if not sql.strip():
        return
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except ParseError:
        return
    for statement in statements:
        if isinstance(statement, exp.Create):
            _handle_create(statement, schema)
        elif isinstance(statement, exp.Alter):
            _handle_alter(statement, schema)
        elif isinstance(statement, exp.Drop):
            _handle_drop(statement, schema)
        elif isinstance(statement, exp.Command):
            _handle_command(statement, schema)
    for table in schema.values():
        table.sync_primary_key_flags()


def load_schema_from_migrations(path: str) -> Schema:
    schema: Schema = {}
    files = sorted(glob.glob(os.path.join(path, "**", "*.sql"), recursive=True))
    for file_path in files:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
            parse_schema_from_sql(handle.read(), schema)
    return schema
