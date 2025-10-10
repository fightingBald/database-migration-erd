"""Schema data structures for ERD generation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple


@dataclass
class Column:
    """A table column definition."""

    name: str
    data_type: str = ""
    nullable: bool = True
    is_primary_key: bool = False


@dataclass
class ForeignKey:
    """A foreign key constraint linking two tables."""

    columns: Tuple[str, ...]
    ref_table: str
    ref_columns: Tuple[str, ...]
    name: Optional[str] = None


@dataclass
class Index:
    """Index metadata, including unique and partial information."""

    name: Optional[str]
    columns: Tuple[str, ...]
    expression_columns: Tuple[str, ...] = field(default_factory=tuple)
    column_names: Tuple[Optional[str], ...] = field(default_factory=tuple)
    unique: bool = False
    method: Optional[str] = None
    where: Optional[str] = None

    def uses_expression(self) -> bool:
        return bool(self.expression_columns)


@dataclass
class Table:
    """A database table comprised of columns and constraints."""

    name: str
    columns: List[Column] = field(default_factory=list)
    primary_key: Set[str] = field(default_factory=set)
    foreign_keys: List[ForeignKey] = field(default_factory=list)
    indexes: List[Index] = field(default_factory=list)
    constraint_types: Dict[str, str] = field(default_factory=dict)
    primary_key_name: Optional[str] = None

    def get_column(self, column_name: str) -> Optional[Column]:
        target = column_name.lower()
        for column in self.columns:
            if column.name.lower() == target:
                return column
        return None

    def add_column(self, column: Column) -> None:
        existing = self.get_column(column.name)
        if existing:
            existing.data_type = column.data_type
            existing.nullable = column.nullable
            existing.is_primary_key = column.is_primary_key
        else:
            self.columns.append(column)
        if column.is_primary_key:
            self.primary_key.add(column.name)
        self.sync_primary_key_flags()

    def add_foreign_key(self, foreign_key: ForeignKey, constraint_name: Optional[str] = None) -> None:
        if constraint_name:
            key = constraint_name.lower()
            foreign_key.name = key
            self.constraint_types[key] = "foreign_key"
        elif foreign_key.name:
            foreign_key.name = foreign_key.name.lower()
            self.constraint_types[foreign_key.name] = "foreign_key"
        self.foreign_keys.append(foreign_key)

    def set_primary_key(self, columns: Iterable[str], constraint_name: Optional[str] = None) -> None:
        self.primary_key = {column for column in columns}
        if constraint_name:
            key = constraint_name.lower()
            self.constraint_types[key] = "primary_key"
            self.primary_key_name = key
        self.sync_primary_key_flags()

    def add_index(
        self,
        index: Index,
        constraint_name: Optional[str] = None,
        constraint_type: str = "index",
    ) -> None:
        name_key: Optional[str] = None
        if constraint_name:
            name_key = constraint_name.lower()
            index.name = name_key
            self.constraint_types[name_key] = constraint_type
        elif index.name:
            name_key = index.name.lower()
            index.name = name_key
        existing = None
        if name_key:
            for idx in self.indexes:
                if (idx.name or "").lower() == name_key:
                    existing = idx
                    break
        if existing:
            existing.columns = index.columns
            existing.expression_columns = index.expression_columns
            existing.column_names = index.column_names
            existing.unique = index.unique
            existing.method = index.method
            existing.where = index.where
        else:
            self.indexes.append(index)

    def drop_column(self, column_name: str) -> None:
        target = column_name.lower()
        self.columns = [column for column in self.columns if column.name.lower() != target]
        self.primary_key = {col for col in self.primary_key if col.lower() != target}
        fk_names = {
            fk.name
            for fk in self.foreign_keys
            if fk.name and target in {col.lower() for col in fk.columns}
        }
        self.foreign_keys = [
            fk for fk in self.foreign_keys if target not in {col.lower() for col in fk.columns}
        ]
        for name in fk_names:
            if name:
                self.constraint_types.pop(name.lower(), None)
        self.indexes = [
            idx
            for idx in self.indexes
            if all((col_name or "").lower() != target for col_name in idx.column_names)
        ]
        if self.primary_key_name and self.primary_key_name not in self.constraint_types:
            self.primary_key_name = None
        self.sync_primary_key_flags()

    def update_nullable(self, column_name: str, nullable: bool) -> None:
        column = self.get_column(column_name)
        if column:
            column.nullable = nullable

    def update_data_type(self, column_name: str, data_type: str) -> None:
        column = self.get_column(column_name)
        if column and data_type:
            column.data_type = data_type.strip()

    def drop_constraint(self, constraint_name: str) -> None:
        key = constraint_name.lower()
        constraint_type = self.constraint_types.pop(key, None)
        if constraint_type == "primary_key":
            self.primary_key.clear()
            self.primary_key_name = None
            self.sync_primary_key_flags()
        elif constraint_type == "foreign_key":
            self.foreign_keys = [fk for fk in self.foreign_keys if (fk.name or "").lower() != key]
        elif constraint_type == "unique":
            self.indexes = [idx for idx in self.indexes if (idx.name or "").lower() != key]

    def rename_constraint(self, old_name: str, new_name: str) -> None:
        old_key = old_name.lower()
        constraint_type = self.constraint_types.pop(old_key, None)
        if not constraint_type:
            return
        new_key = new_name.lower()
        self.constraint_types[new_key] = constraint_type
        if constraint_type == "primary_key":
            self.primary_key_name = new_key
        elif constraint_type == "foreign_key":
            for fk in self.foreign_keys:
                if (fk.name or "").lower() == old_key:
                    fk.name = new_key
                    break
        elif constraint_type == "unique":
            for idx in self.indexes:
                if (idx.name or "").lower() == old_key:
                    idx.name = new_key
                    break

    def rename_column(self, old_name: str, new_name: str) -> None:
        old_key = old_name.lower()
        for column in self.columns:
            if column.name.lower() == old_key:
                column.name = new_name
        updated_pk: Set[str] = set()
        for column in self.primary_key:
            if column.lower() == old_key:
                updated_pk.add(new_name)
            else:
                updated_pk.add(column)
        self.primary_key = updated_pk
        for fk in self.foreign_keys:
            fk.columns = tuple(new_name if col.lower() == old_key else col for col in fk.columns)
            if fk.ref_table == self.name:
                fk.ref_columns = tuple(new_name if col.lower() == old_key else col for col in fk.ref_columns)
        for idx in self.indexes:
            columns = list(idx.columns)
            column_names = list(idx.column_names or ())
            if column_names and len(column_names) != len(columns):
                column_names = [col.lower() if col else None for col in columns]
            changed = False
            for i, col_name in enumerate(column_names):
                if col_name and col_name.lower() == old_key:
                    columns[i] = new_name.upper()
                    column_names[i] = new_name.lower()
                    changed = True
            if changed:
                idx.columns = tuple(columns)
                idx.column_names = tuple(column_names)
        self.sync_primary_key_flags()

    def drop_index(self, index_name: str) -> bool:
        key = index_name.lower()
        removed = False
        remaining = []
        for idx in self.indexes:
            if (idx.name or "").lower() == key:
                removed = True
                continue
            remaining.append(idx)
        if removed:
            self.indexes = remaining
            self.constraint_types.pop(key, None)
        return removed

    def rename_index(self, old_name: str, new_name: str) -> bool:
        old_key = old_name.lower()
        new_key = new_name.lower()
        for idx in self.indexes:
            if (idx.name or "").lower() == old_key:
                idx.name = new_key
                self.constraint_types[new_key] = self.constraint_types.pop(old_key, "index")
                return True
        return False

    def sync_primary_key_flags(self) -> None:
        pk_columns = {col.lower() for col in self.primary_key}
        for column in self.columns:
            column.is_primary_key = column.name.lower() in pk_columns


Schema = Dict[str, Table]


def iter_columns(schema: Schema) -> Iterable[Column]:
    for table in schema.values():
        yield from table.columns


def iter_foreign_keys(schema: Schema) -> Iterable[ForeignKey]:
    for table in schema.values():
        yield from table.foreign_keys


def rename_table(schema: Schema, old_name: str, new_name: str) -> None:
    table = schema.pop(old_name, None)
    if table is None:
        return
    table.name = new_name
    schema[new_name] = table
    for other in schema.values():
        for fk in other.foreign_keys:
            if fk.ref_table == old_name:
                fk.ref_table = new_name


def rename_column_in_schema(schema: Schema, table_name: str, old_name: str, new_name: str) -> None:
    table = schema.get(table_name)
    if not table:
        return
    table.rename_column(old_name, new_name)
    for other in schema.values():
        if other.name == table_name:
            continue
        for fk in other.foreign_keys:
            if fk.ref_table == table_name:
                fk.ref_columns = tuple(
                    new_name if col.lower() == old_name.lower() else col for col in fk.ref_columns
                )


def describe_indexes(table: Table) -> List[str]:
    lines: List[str] = []
    if table.primary_key:
        pk_cols = ", ".join(sorted(col.upper() for col in table.primary_key))
        label = table.primary_key_name.upper() if table.primary_key_name else "PK"
        lines.append(f"{label}: ({pk_cols})")
    for index in table.indexes:
        cols = ", ".join(index.columns)
        prefix = f"{index.name.upper()}: " if index.name else ""
        status = []
        if index.unique:
            status.append("UNIQUE")
        if index.method:
            status.append(index.method.upper())
        if index.uses_expression():
            status.append("EXPRESSION")
        status_prefix = f"{' '.join(status)} " if status else ""
        where = f" WHERE {index.where}" if index.where else ""
        lines.append(f"{prefix}{status_prefix}({cols}){where}")
    return lines
