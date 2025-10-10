"""Minimal SQL parser to pull schema information from migration files."""
from __future__ import annotations

import glob
import os
import re
from typing import List

from .schema import (
    Column,
    ForeignKey,
    Schema,
    Table,
    rename_column_in_schema,
    rename_table,
)


CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>\"[^\"]+\"|[a-zA-Z_][\w.]*)\s*\((?P<body>.*)\)",
    re.IGNORECASE | re.DOTALL,
)
DROP_TABLE_RE = re.compile(
    r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?P<name>\"[^\"]+\"|[a-zA-Z_][\w.]*)"
    r"(?:\s+(?:CASCADE|RESTRICT))?",
    re.IGNORECASE,
)
ALTER_TABLE_RE = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?P<table>\"[^\"]+\"|[a-zA-Z_][\w.]*)\s+(?P<actions>.*)",
    re.IGNORECASE | re.DOTALL,
)
PRIMARY_KEY_RE = re.compile(r"PRIMARY\s+KEY\s*\((?P<cols>[^)]+)\)", re.IGNORECASE | re.DOTALL)
TABLE_FOREIGN_KEY_RE = re.compile(
    r"FOREIGN\s+KEY\s*\((?P<src>[^)]+)\)\s*REFERENCES\s+"
    r"(?P<ref_table>\"[^\"]+\"|[a-zA-Z_][\w.]*)\s*\((?P<ref>[^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)
COLUMN_INLINE_FOREIGN_KEY_RE = re.compile(
    r"(?:CONSTRAINT\s+(?P<name>\"[^\"]+\"|[a-zA-Z_][\w]*)\s+)?REFERENCES\s+"
    r"(?P<table>\"[^\"]+\"|[a-zA-Z_][\w.]*)\s*\((?P<cols>[^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)
COLUMN_INLINE_PRIMARY_KEY_RE = re.compile(
    r"(?:CONSTRAINT\s+(?P<name>\"[^\"]+\"|[a-zA-Z_][\w]*)\s+)?PRIMARY\s+KEY",
    re.IGNORECASE,
)
ADD_COLUMN_RE = re.compile(
    r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<definition>.+)",
    re.IGNORECASE | re.DOTALL,
)
DROP_COLUMN_RE = re.compile(
    r"DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?(?P<name>\"[^\"]+\"|[a-zA-Z_][\w]*)"
    r"(?:\s+(?:CASCADE|RESTRICT))?",
    re.IGNORECASE,
)
ALTER_COLUMN_SET_NOT_NULL_RE = re.compile(
    r"ALTER\s+COLUMN\s+(?P<name>\"[^\"]+\"|[a-zA-Z_][\w]*)\s+SET\s+NOT\s+NULL",
    re.IGNORECASE,
)
ALTER_COLUMN_DROP_NOT_NULL_RE = re.compile(
    r"ALTER\s+COLUMN\s+(?P<name>\"[^\"]+\"|[a-zA-Z_][\w]*)\s+DROP\s+NOT\s+NULL",
    re.IGNORECASE,
)
ALTER_COLUMN_TYPE_RE = re.compile(
    r"ALTER\s+COLUMN\s+(?P<name>\"[^\"]+\"|[a-zA-Z_][\w]*)\s+TYPE\s+(?P<type>.+)",
    re.IGNORECASE | re.DOTALL,
)
ADD_CONSTRAINT_RE = re.compile(
    r"ADD\s+CONSTRAINT\s+(?P<name>\"[^\"]+\"|[a-zA-Z_][\w]*)\s+(?P<definition>.+)",
    re.IGNORECASE | re.DOTALL,
)
DROP_CONSTRAINT_RE = re.compile(
    r"DROP\s+CONSTRAINT\s+(?:IF\s+EXISTS\s+)?(?P<name>\"[^\"]+\"|[a-zA-Z_][\w]*)"
    r"(?:\s+(?:CASCADE|RESTRICT))?",
    re.IGNORECASE,
)
RENAME_COLUMN_RE = re.compile(
    r"RENAME\s+COLUMN\s+(?P<old>\"[^\"]+\"|[a-zA-Z_][\w]*)\s+TO\s+(?P<new>\"[^\"]+\"|[a-zA-Z_][\w]*)",
    re.IGNORECASE,
)
RENAME_CONSTRAINT_RE = re.compile(
    r"RENAME\s+CONSTRAINT\s+(?P<old>\"[^\"]+\"|[a-zA-Z_][\w]*)\s+TO\s+(?P<new>\"[^\"]+\"|[a-zA-Z_][\w]*)",
    re.IGNORECASE,
)
RENAME_TABLE_RE = re.compile(
    r"RENAME\s+TO\s+(?P<new>\"[^\"]+\"|[a-zA-Z_][\w.]*)",
    re.IGNORECASE,
)
CONSTRAINT_NAME_RE = re.compile(
    r"CONSTRAINT\s+(?P<name>\"[^\"]+\"|[a-zA-Z_][\w]*)\s+(?P<rest>.*)",
    re.IGNORECASE | re.DOTALL,
)
COMMENT_LINE_RE = re.compile(r"--.*?$", re.MULTILINE)
COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
STOP_WORDS = {
    "PRIMARY",
    "REFERENCES",
    "NOT",
    "NULL",
    "DEFAULT",
    "UNIQUE",
    "CHECK",
    "CONSTRAINT",
    "GENERATED",
    "AS",
}


def strip_comments(sql: str) -> str:
    sql = COMMENT_BLOCK_RE.sub("", sql)
    return COMMENT_LINE_RE.sub("", sql)


def split_top_level_commas(text: str) -> List[str]:
    parts: List[str] = []
    buf: List[str] = []
    depth = 0
    in_single = False
    in_double = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "'" and not in_double:
            if in_single and i + 1 < len(text) and text[i + 1] == "'":
                buf.append("''")
                i += 2
                continue
            in_single = not in_single
        elif ch == '"' and not in_single:
            if in_double and i + 1 < len(text) and text[i + 1] == '"':
                buf.append('""')
                i += 2
                continue
            in_double = not in_double
        elif ch == "(" and not in_single and not in_double:
            depth += 1
        elif ch == ")" and not in_single and not in_double and depth > 0:
            depth -= 1
        if ch == "," and depth == 0 and not in_single and not in_double:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def split_sql_statements(sql: str) -> List[str]:
    statements: List[str] = []
    buf: List[str] = []
    in_single = False
    in_double = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_double:
            if in_single and i + 1 < len(sql) and sql[i + 1] == "'":
                buf.append("''")
                i += 2
                continue
            in_single = not in_single
        elif ch == '"' and not in_single:
            if in_double and i + 1 < len(sql) and sql[i + 1] == '"':
                buf.append('""')
                i += 2
                continue
            in_double = not in_double
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


def split_identifier_list(raw: str) -> List[str]:
    return [normalize_identifier(chunk) for chunk in raw.split(",") if chunk.strip()]


def normalize_identifier(identifier: str) -> str:
    identifier = identifier.strip()
    if not identifier:
        return identifier
    parts = identifier.split(".")
    normalized = []
    for part in parts:
        part = part.strip()
        if part.startswith('"') and part.endswith('"'):
            normalized.append(part[1:-1])
        else:
            normalized.append(part.lower())
    return ".".join(normalized)


def extract_constraint_name(definition: str) -> tuple[str | None, str]:
    definition = definition.strip()
    match = CONSTRAINT_NAME_RE.match(definition)
    if match:
        name = normalize_identifier(match.group("name"))
        rest = match.group("rest").strip()
        return name, rest
    return None, definition


def parse_column_definition(item: str, table: Table) -> None:
    item = item.strip()
    if not item or item.upper().startswith(("CONSTRAINT", "PRIMARY", "FOREIGN", "UNIQUE", "CHECK")):
        return

    match = re.match(r"^(\"[^\"]+\"|[a-zA-Z_][\w]*)\s+(?P<rest>.*)$", item, re.DOTALL)
    if not match:
        return

    raw_name = match.group(1)
    rest = match.group("rest").strip()
    name = normalize_identifier(raw_name)

    column = Column(name=name)
    tokens = rest.split()
    type_parts: List[str] = []
    for token in tokens:
        if token.upper() in STOP_WORDS:
            break
        type_parts.append(token)
    column.data_type = " ".join(type_parts)
    column.nullable = "NOT NULL" not in rest.upper()
    column.is_primary_key = "PRIMARY KEY" in rest.upper()

    table.add_column(column)

    if column.is_primary_key:
        pk_constraint_match = COLUMN_INLINE_PRIMARY_KEY_RE.search(rest)
        pk_constraint = (
            normalize_identifier(pk_constraint_match.group("name"))
            if pk_constraint_match and pk_constraint_match.group("name")
            else None
        )
        if pk_constraint:
            table.set_primary_key(table.primary_key, constraint_name=pk_constraint)

    fk_match = COLUMN_INLINE_FOREIGN_KEY_RE.search(rest)
    if fk_match:
        fk_name = fk_match.group("name")
        constraint_name = normalize_identifier(fk_name) if fk_name else None
        ref_table = normalize_identifier(fk_match.group("table"))
        ref_cols = tuple(split_identifier_list(fk_match.group("cols")))
        table.add_foreign_key(
            ForeignKey(columns=(column.name,), ref_table=ref_table, ref_columns=ref_cols),
            constraint_name=constraint_name,
        )


def parse_table_constraint(item: str, table: Table) -> None:
    constraint_name, definition = extract_constraint_name(item)

    pk_match = PRIMARY_KEY_RE.search(definition)
    if pk_match:
        table.set_primary_key(split_identifier_list(pk_match.group("cols")), constraint_name)

    fk_match = TABLE_FOREIGN_KEY_RE.search(definition)
    if fk_match:
        src_cols = tuple(split_identifier_list(fk_match.group("src")))
        ref_table = normalize_identifier(fk_match.group("ref_table"))
        ref_cols = tuple(split_identifier_list(fk_match.group("ref")))
        table.add_foreign_key(
            ForeignKey(columns=src_cols, ref_table=ref_table, ref_columns=ref_cols),
            constraint_name=constraint_name,
        )


def parse_create_table_statement(statement: str, schema: Schema) -> None:
    stmt = statement.strip()
    stmt_with_semicolon = stmt if stmt.endswith(";") else f"{stmt};"
    match = CREATE_TABLE_RE.search(stmt_with_semicolon)
    if not match:
        return

    table_name = normalize_identifier(match.group("name"))
    body = match.group("body")
    table = schema.get(table_name)
    if table is None:
        table = Table(name=table_name)
        schema[table_name] = table
    table.columns.clear()
    table.primary_key.clear()
    table.foreign_keys.clear()
    table.constraint_types.clear()
    table.primary_key_name = None

    items = split_top_level_commas(body)
    for item in items:
        parse_column_definition(item, table)
    for item in items:
        parse_table_constraint(item, table)
    table.sync_primary_key_flags()


def apply_alter_table_action(action: str, table: Table, schema: Schema) -> str | None:
    action = action.strip()
    if not action:
        return None

    add_column_match = ADD_COLUMN_RE.match(action)
    if add_column_match:
        definition = add_column_match.group("definition").strip()
        parse_column_definition(definition, table)
        return None

    drop_column_match = DROP_COLUMN_RE.match(action)
    if drop_column_match:
        column_name = normalize_identifier(drop_column_match.group("name"))
        table.drop_column(column_name)
        return None

    set_not_null_match = ALTER_COLUMN_SET_NOT_NULL_RE.match(action)
    if set_not_null_match:
        column_name = normalize_identifier(set_not_null_match.group("name"))
        table.update_nullable(column_name, False)
        return None

    drop_not_null_match = ALTER_COLUMN_DROP_NOT_NULL_RE.match(action)
    if drop_not_null_match:
        column_name = normalize_identifier(drop_not_null_match.group("name"))
        table.update_nullable(column_name, True)
        return None

    alter_type_match = ALTER_COLUMN_TYPE_RE.match(action)
    if alter_type_match:
        column_name = normalize_identifier(alter_type_match.group("name"))
        type_definition = alter_type_match.group("type").strip()
        upper_type = type_definition.upper()
        if " USING " in upper_type:
            using_index = upper_type.index(" USING ")
            type_definition = type_definition[:using_index].strip()
        table.update_data_type(column_name, type_definition)
        return None

    add_constraint_match = ADD_CONSTRAINT_RE.match(action)
    if add_constraint_match:
        constraint_name = normalize_identifier(add_constraint_match.group("name"))
        definition = add_constraint_match.group("definition").strip()
        parse_table_constraint(f"CONSTRAINT {constraint_name} {definition}", table)
        table.sync_primary_key_flags()
        return None

    if action.upper().startswith("ADD PRIMARY KEY"):
        parse_table_constraint(action[len("ADD "):], table)
        table.sync_primary_key_flags()
        return None

    if action.upper().startswith("ADD FOREIGN KEY"):
        definition = action[len("ADD "):].strip()
        parse_table_constraint(definition, table)
        return None

    drop_constraint_match = DROP_CONSTRAINT_RE.match(action)
    if drop_constraint_match:
        constraint_name = normalize_identifier(drop_constraint_match.group("name"))
        table.drop_constraint(constraint_name)
        return None

    rename_constraint_match = RENAME_CONSTRAINT_RE.match(action)
    if rename_constraint_match:
        old_name = normalize_identifier(rename_constraint_match.group("old"))
        new_name = normalize_identifier(rename_constraint_match.group("new"))
        table.rename_constraint(old_name, new_name)
        return None

    rename_column_match = RENAME_COLUMN_RE.match(action)
    if rename_column_match:
        old_column = normalize_identifier(rename_column_match.group("old"))
        new_column = normalize_identifier(rename_column_match.group("new"))
        rename_column_in_schema(schema, table.name, old_column, new_column)
        return None

    rename_table_match = RENAME_TABLE_RE.match(action)
    if rename_table_match:
        new_table_name = normalize_identifier(rename_table_match.group("new"))
        if new_table_name != table.name:
            rename_table(schema, table.name, new_table_name)
            return new_table_name
        return None

    return None


def parse_alter_table_statement(statement: str, schema: Schema) -> None:
    stmt = statement.strip()
    stmt_with_semicolon = stmt if stmt.endswith(";") else f"{stmt};"
    match = ALTER_TABLE_RE.match(stmt_with_semicolon)
    if not match:
        return

    table_name = normalize_identifier(match.group("table"))
    actions_raw = match.group("actions").strip()
    if actions_raw.endswith(";"):
        actions_raw = actions_raw[:-1].strip()
    table = schema.setdefault(table_name, Table(name=table_name))

    actions = split_top_level_commas(actions_raw)
    if not actions:
        actions = [actions_raw]

    current_table_name = table_name
    current_table = table

    for action in actions:
        new_name = apply_alter_table_action(action, current_table, schema)
        if new_name:
            current_table_name = new_name
            current_table = schema.setdefault(current_table_name, Table(name=current_table_name))
    current_table.sync_primary_key_flags()


def parse_drop_table_statement(statement: str, schema: Schema) -> None:
    stmt = statement.strip()
    match = DROP_TABLE_RE.match(stmt)
    if not match:
        return

    table_name = normalize_identifier(match.group("name"))
    if table_name in schema:
        schema.pop(table_name, None)
        for table in schema.values():
            table.foreign_keys = [fk for fk in table.foreign_keys if fk.ref_table != table_name]
            table.constraint_types = {
                name: ctype
                for name, ctype in table.constraint_types.items()
                if not (ctype == "foreign_key" and any((fk.name or "").lower() == name for fk in table.foreign_keys))
            }


def parse_schema_from_sql(sql: str, schema: Schema) -> None:
    sql = strip_comments(sql)
    for statement in split_sql_statements(sql):
        upper_stmt = statement.lstrip().upper()
        if upper_stmt.startswith("CREATE TABLE"):
            parse_create_table_statement(statement, schema)
        elif upper_stmt.startswith("ALTER TABLE"):
            parse_alter_table_statement(statement, schema)
        elif upper_stmt.startswith("DROP TABLE"):
            parse_drop_table_statement(statement, schema)


def load_schema_from_migrations(path: str) -> Schema:
    schema: Schema = {}
    files = sorted(glob.glob(os.path.join(path, "**", "*.sql"), recursive=True))
    for file_path in files:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
            parse_schema_from_sql(handle.read(), schema)
    for table in schema.values():
        table.sync_primary_key_flags()
    return schema
