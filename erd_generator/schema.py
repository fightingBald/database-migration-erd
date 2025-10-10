"""Schema data structures for ERD generation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Set, Tuple


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
    name: str | None = None


@dataclass
class Table:
    """A database table comprised of columns and constraints."""

    name: str
    columns: List[Column] = field(default_factory=list)
    primary_key: Set[str] = field(default_factory=set)
    foreign_keys: List[ForeignKey] = field(default_factory=list)
    constraint_types: Dict[str, str] = field(default_factory=dict)
    primary_key_name: str | None = None

    def get_column(self, column_name: str) -> Column | None:
        target = column_name.lower()
        for column in self.columns:
            if column.name.lower() == target:
                return column
        return None

    def has_column(self, column_name: str) -> bool:
        return self.get_column(column_name) is not None

    def register_constraint(self, constraint_name: str, constraint_type: str) -> str:
        key = constraint_name.lower()
        self.constraint_types[key] = constraint_type
        return key

    def set_primary_key(self, columns: Iterable[str], constraint_name: str | None = None) -> None:
        self.primary_key = {column for column in columns}
        if constraint_name:
            key = self.register_constraint(constraint_name, "primary_key")
            if self.primary_key_name and self.primary_key_name != key:
                self.constraint_types.pop(self.primary_key_name, None)
            self.primary_key_name = key
        self.sync_primary_key_flags()

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

    def add_foreign_key(self, foreign_key: ForeignKey, constraint_name: str | None = None) -> None:
        if constraint_name:
            key = self.register_constraint(constraint_name, "foreign_key")
            foreign_key.name = key
        elif foreign_key.name:
            foreign_key.name = foreign_key.name.lower()
            self.constraint_types[foreign_key.name] = "foreign_key"
        self.foreign_keys.append(foreign_key)

    def drop_column(self, column_name: str) -> None:
        target = column_name.lower()
        self.columns = [column for column in self.columns if column.name.lower() != target]
        self.primary_key = {col for col in self.primary_key if col.lower() != target}
        removed_fk_names = {
            fk.name for fk in self.foreign_keys if fk.name and target in {col.lower() for col in fk.columns}
        }
        self.foreign_keys = [
            fk for fk in self.foreign_keys if target not in {col.lower() for col in fk.columns}
        ]
        for name in removed_fk_names:
            self.constraint_types.pop(name.lower(), None)
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
        self.sync_primary_key_flags()

    def sync_primary_key_flags(self) -> None:
        """Ensure column instances know whether they participate in the PK."""
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
    old_key = old_name
    table = schema.pop(old_key, None)
    if table is None:
        return
    table.name = new_name
    schema[new_name] = table
    for other in schema.values():
        for fk in other.foreign_keys:
            if fk.ref_table == old_key:
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
