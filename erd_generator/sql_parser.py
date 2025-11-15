"""SQL parsing helpers backed by sqlglot."""
from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

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
# Failure tracking


@dataclass(frozen=True)
class ParseFailure:
    source: Optional[str]
    sql: str
    reason: str


_LAST_PARSE_FAILURES: List[ParseFailure] = []


def _clean_sql_snippet(sql_text: str, limit: int = 200) -> str:
    snippet = " ".join(sql_text.strip().split())
    if len(snippet) > limit:
        return f"{snippet[: limit - 3]}..."
    return snippet


def _record_failure(
    failures: Optional[List[ParseFailure]],
    source: Optional[str],
    sql_text: str,
    reason: str,
) -> None:
    snippet = _clean_sql_snippet(sql_text)
    location = source or "<input>"
    print(f"[WARN] {reason} in {location}: {snippet}")
    if failures is not None:
        failures.append(ParseFailure(source=source, sql=snippet, reason=reason))


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


def _extract_fk_hints(raw_sql: str) -> List[Tuple[str, str, Tuple[str, ...]]]:
    hints: List[Tuple[str, str, Tuple[str, ...]]] = []
    fk_pattern = re.compile(
        r"--\s*FK\s+(?P<table>[^(]+?)\s*\((?P<cols>[^)]*)\)",
        re.IGNORECASE,
    )
    column_pattern = re.compile(r'^\s*(?P<name>"[^"]+"|[A-Za-z_][\w]*)')

    for line in raw_sql.splitlines():
        match = fk_pattern.search(line)
        if not match:
            continue
        before_comment = line[: match.start()]
        column_match = column_pattern.match(before_comment)
        if not column_match:
            continue
        local_column = _column_name(column_match.group("name"))
        ref_table = _table_name(match.group("table"))
        ref_columns_raw = match.group("cols")
        ref_columns: Tuple[str, ...] = tuple(
            _column_name(part) for part in ref_columns_raw.split(",") if part.strip()
        )
        hints.append((local_column, ref_table, ref_columns))
    return hints


def _apply_fk_hints(table: Table, hints: Iterable[Tuple[str, str, Tuple[str, ...]]]) -> None:
    for local_column, ref_table, ref_columns in hints:
        if not local_column or not ref_table:
            continue
        local_columns = (local_column,)
        target_columns = ref_columns or local_columns
        exists = any(
            fk.columns == local_columns and fk.ref_table == ref_table and fk.ref_columns == target_columns
            for fk in table.foreign_keys
        )
        if exists:
            continue
        table.add_foreign_key(
            ForeignKey(columns=local_columns, ref_table=ref_table, ref_columns=target_columns)
        )


def _handle_create_table(statement: exp.Create, schema: Schema, raw_sql: Optional[str] = None) -> None:
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
    if raw_sql:
        hints = _extract_fk_hints(raw_sql)
        _apply_fk_hints(table, hints)
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


def _handle_create(
    statement: exp.Create,
    schema: Schema,
    raw_sql: Optional[str] = None,
    *,
    source: Optional[str] = None,
    failures: Optional[List[ParseFailure]] = None,
) -> None:
    kind = (statement.args.get("kind") or "").upper()
    has_expression = statement.args.get("expression") is not None
    if kind == "TABLE" and not has_expression:
        _handle_create_table(statement, schema, raw_sql)
    elif kind == "INDEX":
        _handle_create_index(statement, schema)
    else:
        snippet = raw_sql or statement.sql(dialect="postgres")
        _record_failure(
            failures,
            source,
            snippet,
            f"Unsupported CREATE {kind or 'statement'}",
        )


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


def _handle_command(command: exp.Command, schema: Schema) -> bool:
    sql_text = command.sql(dialect="postgres")
    match = RENAME_CONSTRAINT_RE.match(sql_text)
    if not match:
        return False
    table_name = _normalize_identifier(match.group("table"))
    old_name = _normalize_identifier(match.group("old"))
    new_name = _normalize_identifier(match.group("new"))
    table = schema.setdefault(table_name, Table(name=table_name))
    table.rename_constraint(old_name, new_name)
    return True


# ---------------------------------------------------------------------------
# Public API


def _split_sql_statements(sql: str) -> List[str]:
    statements: List[str] = []
    buf: List[str] = []
    in_single = False
    in_double = False
    i = 0
    length = len(sql)
    while i < length:
        ch = sql[i]
        next_two = sql[i : i + 2]
        if ch == "'" and not in_double:
            if in_single and i + 1 < length and sql[i + 1] == "'":
                buf.append("''")
                i += 2
                continue
            in_single = not in_single
            buf.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            if in_double and i + 1 < length and sql[i + 1] == '"':
                buf.append('""')
                i += 2
                continue
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue
        if not in_single and not in_double and next_two == "--":
            newline_index = sql.find("\n", i)
            if newline_index == -1:
                buf.append(sql[i:])
                i = length
                break
            buf.append(sql[i:newline_index])
            i = newline_index
            continue
        if not in_single and not in_double and next_two == "/*":
            end_index = sql.find("*/", i + 2)
            if end_index == -1:
                buf.append(sql[i:])
                i = length
                break
            end_index += 2
            buf.append(sql[i:end_index])
            i = end_index
            continue
        if ch == ";" and not in_single and not in_double:
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def parse_schema_from_sql(
    sql: str,
    schema: Schema,
    *,
    source: Optional[str] = None,
    failures: Optional[List[ParseFailure]] = None,
) -> None:
    if not sql.strip():
        return
    for raw_statement in _split_sql_statements(sql):
        try:
            expressions = sqlglot.parse(raw_statement, read="postgres")
        except (ParseError, TokenError) as exc:
            _record_failure(
                failures,
                source,
                raw_statement,
                f"Parse error ({exc.__class__.__name__})",
            )
            continue
        for statement in expressions:
            if isinstance(statement, exp.Create):
                _handle_create(
                    statement,
                    schema,
                    raw_statement,
                    source=source,
                    failures=failures,
                )
            elif isinstance(statement, exp.Alter):
                _handle_alter(statement, schema)
            elif isinstance(statement, exp.Drop):
                _handle_drop(statement, schema)
            elif isinstance(statement, exp.Command):
                handled = _handle_command(statement, schema)
                reason = "Parsed via generic command handler" if handled else "Unsupported SQL command"
                _record_failure(
                    failures,
                    source,
                    statement.sql(dialect="postgres"),
                    reason,
                )
    for table in schema.values():
        table.sync_primary_key_flags()


def load_schema_from_migrations(path: str) -> Schema:
    schema: Schema = {}
    global _LAST_PARSE_FAILURES
    _LAST_PARSE_FAILURES = []
    files = sorted(glob.glob(os.path.join(path, "**", "*.sql"), recursive=True))
    for file_path in files:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
            parse_schema_from_sql(
                handle.read(),
                schema,
                source=file_path,
                failures=_LAST_PARSE_FAILURES,
            )
    return schema


def get_last_parse_failures() -> List[ParseFailure]:
    return list(_LAST_PARSE_FAILURES)
