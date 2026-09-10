"""Validate schema relationships without inventing graph objects or changing SQL metadata."""

from dataclasses import dataclass

from .schema import Schema, Table


@dataclass(frozen=True, order=True)
class Relationship:
    table: str
    columns: tuple[str, ...]
    ref_table: str
    ref_columns: tuple[str, ...]
    name: str = ""


@dataclass(frozen=True)
class SchemaValidation:
    relationships: tuple[Relationship, ...]
    errors: tuple[str, ...]


def primary_columns(table: Table) -> set[str]:
    return table.primary_key | {c.name for c in table.columns if c.is_primary_key}


def validate_schema(schema: Schema) -> SchemaValidation:
    errors = []
    relations = {}
    if not schema:
        errors.append("no tables to generate")
    for key, table in sorted(schema.items()):
        if not key or key != table.name:
            errors.append(f"table key {key!r} does not match a nonempty table name")
        names = [c.name for c in table.columns]
        if any(not name for name in names):
            errors.append(f"{key}: empty column name")
        if len(set(names)) != len(names):
            errors.append(f"{key}: duplicate column names")
        if primary_columns(table) - set(names):
            errors.append(f"{key}: primary key references an unknown column")
        for fk in table.foreign_keys:
            context = f"{key} FK {fk.name or fk.columns}"
            if not fk.columns:
                errors.append(f"{context}: empty foreign key")
                continue
            target = schema.get(fk.ref_table)
            if target is None:
                errors.append(f"{context}: unknown target table {fk.ref_table!r}")
                continue
            refs = fk.ref_columns
            if not refs:
                primary = primary_columns(target)
                if len(primary) != 1:
                    errors.append(
                        f"{context}: implicit composite or absent primary key; supply reference columns explicitly"
                    )
                    continue
                refs = tuple(primary)
            if len(fk.columns) != len(refs):
                errors.append(f"{context}: mismatched column counts")
                continue
            if any(column not in names for column in fk.columns):
                errors.append(f"{context}: unknown source column")
                continue
            target_names = {c.name for c in target.columns}
            if any(column not in target_names for column in refs):
                errors.append(f"{context}: unknown target column")
                continue
            identity = (key, fk.columns, fk.ref_table, refs)
            name = fk.name or ""
            # Keep one relationship for duplicate declarations, independent of input order.
            if identity not in relations or name < relations[identity].name:
                relations[identity] = Relationship(*identity, name)
    return SchemaValidation(tuple(sorted(relations.values())), tuple(errors))
