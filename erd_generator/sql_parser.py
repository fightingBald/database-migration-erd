"""Minimal SQL parser to pull schema information from migration files."""
from __future__ import annotations

import glob
import os
import re
from typing import List

from .schema import Column, ForeignKey, Schema, Table


CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>\"[^\"]+\"|[a-zA-Z_][\w.]*)\s*\((?P<body>.*?)\);",
    re.IGNORECASE | re.DOTALL,
)
ALTER_TABLE_FK_RE = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?P<table>\"[^\"]+\"|[a-zA-Z_][\w.]*)\s+ADD\s+CONSTRAINT\s+" \
    r"[a-zA-Z_][\w]*\s+FOREIGN\s+KEY\s*\((?P<src>.*?)\)\s+REFERENCES\s+" \
    r"(?P<ref_table>\"[^\"]+\"|[a-zA-Z_][\w.]*)\s*\((?P<ref>.*?)\)",
    re.IGNORECASE | re.DOTALL,
)
PRIMARY_KEY_RE = re.compile(r"PRIMARY\s+KEY\s*\((?P<cols>[^)]+)\)", re.IGNORECASE | re.DOTALL)
TABLE_FOREIGN_KEY_RE = re.compile(
    r"FOREIGN\s+KEY\s*\((?P<src>[^)]+)\)\s*REFERENCES\s+" \
    r"(?P<ref_table>\"[^\"]+\"|[a-zA-Z_][\w.]*)\s*\((?P<ref>[^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)
INLINE_FOREIGN_KEY_RE = re.compile(
    r"REFERENCES\s+(?P<table>\"[^\"]+\"|[a-zA-Z_][\w.]*)\s*\((?P<cols>[^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)
COMMENT_LINE_RE = re.compile(r"--.*?$", re.MULTILINE)
COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
STOP_WORDS = {"PRIMARY", "REFERENCES", "NOT", "NULL", "DEFAULT", "UNIQUE", "CHECK", "CONSTRAINT", "GENERATED", "AS"}


def strip_comments(sql: str) -> str:
    sql = COMMENT_BLOCK_RE.sub("", sql)
    return COMMENT_LINE_RE.sub("", sql)


def split_top_level_commas(text: str) -> List[str]:
    parts: List[str] = []
    buf: List[str] = []
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


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

    table.columns.append(column)
    if column.is_primary_key:
        table.primary_key.add(column.name)

    fk_match = INLINE_FOREIGN_KEY_RE.search(rest)
    if fk_match:
        ref_table = normalize_identifier(fk_match.group("table"))
        ref_cols = tuple(split_identifier_list(fk_match.group("cols")))
        table.foreign_keys.append(
            ForeignKey(columns=(column.name,), ref_table=ref_table, ref_columns=ref_cols)
        )


def parse_table_constraint(item: str, table: Table) -> None:
    pk_match = PRIMARY_KEY_RE.search(item)
    if pk_match:
        for col in split_identifier_list(pk_match.group("cols")):
            table.primary_key.add(col)

    fk_match = TABLE_FOREIGN_KEY_RE.search(item)
    if fk_match:
        src_cols = tuple(split_identifier_list(fk_match.group("src")))
        ref_table = normalize_identifier(fk_match.group("ref_table"))
        ref_cols = tuple(split_identifier_list(fk_match.group("ref")))
        table.foreign_keys.append(ForeignKey(columns=src_cols, ref_table=ref_table, ref_columns=ref_cols))


def parse_create_table(sql: str, schema: Schema) -> None:
    for match in CREATE_TABLE_RE.finditer(sql):
        table_name = normalize_identifier(match.group("name"))
        body = match.group("body")
        table = schema.get(table_name)
        if table is None:
            table = Table(name=table_name)
            schema[table_name] = table
        table.columns.clear()
        table.primary_key.clear()
        table.foreign_keys.clear()

        items = split_top_level_commas(body)
        for item in items:
            parse_column_definition(item, table)
        for item in items:
            parse_table_constraint(item, table)


def parse_alter_table(sql: str, schema: Schema) -> None:
    for match in ALTER_TABLE_FK_RE.finditer(sql):
        table_name = normalize_identifier(match.group("table"))
        table = schema.setdefault(table_name, Table(name=table_name))
        src_cols = tuple(split_identifier_list(match.group("src")))
        ref_table = normalize_identifier(match.group("ref_table"))
        ref_cols = tuple(split_identifier_list(match.group("ref")))
        table.foreign_keys.append(ForeignKey(columns=src_cols, ref_table=ref_table, ref_columns=ref_cols))


def parse_schema_from_sql(sql: str, schema: Schema) -> None:
    sql = strip_comments(sql)
    parse_create_table(sql, schema)
    parse_alter_table(sql, schema)


def load_schema_from_migrations(path: str) -> Schema:
    schema: Schema = {}
    files = sorted(glob.glob(os.path.join(path, "**", "*.sql"), recursive=True))
    for file_path in files:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
            parse_schema_from_sql(handle.read(), schema)
    for table in schema.values():
        table.sync_primary_key_flags()
    return schema
