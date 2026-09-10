"""Load YAML relationships; strict resolution is opt-in for the new D2 path."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .diagnostics import ParseFailure
from .schema import ForeignKey, Schema, Table


@dataclass(frozen=True)
class ForeignKeyConfigEntry:
    table_key: str
    normalized_table: str
    local_columns: tuple[str, ...]
    reference_table_key: str
    normalized_reference_table: str
    reference_columns: tuple[str, ...]


def _normalize_identifier(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    return text.lower()


def _normalize_column_sequence(value: Any) -> tuple[str, ...] | None:
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, (list, tuple)) or not values:
        return None
    if any(not isinstance(item, str) or not item.strip() for item in values):
        return None
    return tuple(_normalize_identifier(item) for item in values)


def _record(
    failures: list[ParseFailure] | None, source: str | None, reason: str
) -> None:
    if failures is not None:
        failures.append(ParseFailure(source, "", f"Foreign key config: {reason}"))
    else:
        logging.getLogger(__name__).warning(
            "Foreign key config: %s: %s", source or "<input>", reason
        )


def load_foreign_key_config(
    config_path: str | None,
    failures: list[ParseFailure] | None,
) -> tuple[list[ForeignKeyConfigEntry], str | None]:
    if not config_path:
        return [], None
    path = Path(config_path).expanduser()
    source = str(path)
    try:
        import yaml
    except ImportError:
        _record(failures, source, "PyYAML is not installed")
        return [], source
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        position = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        _record(failures, source, f"invalid YAML{position}")
        return [], source
    except (OSError, UnicodeError) as exc:
        _record(
            failures, source, f"cannot read UTF-8 configuration ({type(exc).__name__})"
        )
        return [], source
    if raw is None:
        return [], source
    if not isinstance(raw, dict):
        _record(failures, source, "top level must map table names to relationships")
        return [], source

    entries = []
    for table_key, payload in raw.items():
        if not isinstance(table_key, str) or not table_key.strip():
            _record(failures, source, "table name must be a nonempty string")
            continue
        if isinstance(payload, dict):
            raw_entries = payload.get("fks", [])
        else:
            raw_entries = payload
        if not isinstance(raw_entries, (list, tuple)):
            _record(failures, source, f"{table_key}: fks must be a sequence")
            continue
        for number, entry in enumerate(raw_entries, 1):
            context = f"{table_key}, relation {number}"
            if isinstance(entry, dict):
                local = (
                    entry.get("columns") or entry.get("local") or entry.get("source")
                )
                target = (
                    entry.get("table")
                    or entry.get("ref_table")
                    or entry.get("references")
                )
                remote = next(
                    (
                        entry[key]
                        for key in ("ref_columns", "target", "targets", "columns_ref")
                        if key in entry
                    ),
                    None,
                )
            elif isinstance(entry, (list, tuple)) and len(entry) in (2, 3):
                local, target = entry[:2]
                remote = entry[2] if len(entry) == 3 else None
            else:
                _record(
                    failures,
                    source,
                    f"{context}: expected a mapping or two/three item sequence",
                )
                continue
            local_columns = _normalize_column_sequence(local)
            if not local_columns:
                _record(failures, source, f"{context}: invalid local columns")
                continue
            if not isinstance(target, str) or not target.strip():
                _record(failures, source, f"{context}: missing reference table")
                continue
            # Preserve the existing two-item YAML shorthand: same column names.
            remote_columns = (
                local_columns if remote is None else _normalize_column_sequence(remote)
            )
            if not remote_columns or len(remote_columns) != len(local_columns):
                _record(
                    failures,
                    source,
                    f"{context}: mismatched or invalid reference columns",
                )
                continue
            entries.append(
                ForeignKeyConfigEntry(
                    table_key,
                    _normalize_identifier(table_key),
                    local_columns,
                    target,
                    _normalize_identifier(target),
                    remote_columns,
                )
            )
    return entries, source


class _SchemaLookup:
    def __init__(self, schema: Schema) -> None:
        self.schema = schema

    def resolve(self, identifier: str, *, strict: bool) -> Table | None:
        # Exact spelling wins for quoted SQL names, before case-insensitive matching.
        if identifier in self.schema:
            return self.schema[identifier]
        matches = [
            t for name, t in self.schema.items() if name.lower() == identifier.lower()
        ]
        if not matches and (not strict or "." not in identifier):
            suffix = identifier.rsplit(".", 1)[-1].lower()
            matches = [
                t
                for name, t in self.schema.items()
                if name.rsplit(".", 1)[-1].lower() == suffix
            ]
        if strict and len(matches) > 1:
            raise ValueError(
                f"ambiguous table '{identifier}'; use an exact qualified name"
            )
        return matches[0] if matches else None


def _resolve_columns(
    table: Table, columns: Iterable[str], *, strict: bool
) -> tuple[str, ...]:
    resolved = []
    for name in columns:
        exact = [c for c in table.columns if c.name == name]
        matches = exact or [c for c in table.columns if c.name.lower() == name.lower()]
        if strict and len(matches) != 1:
            raise ValueError(f"unknown or ambiguous column '{table.name}.{name}'")
        resolved.append(matches[0].name if matches else name)
    return tuple(resolved)


def apply_foreign_key_config(
    schema: Schema,
    entries: Iterable[ForeignKeyConfigEntry],
    *,
    config_source: str | None = None,
    failures: list[ParseFailure] | None = None,
    strict: bool = False,
) -> None:
    lookup = _SchemaLookup(schema)
    for entry in entries:
        try:
            table = lookup.resolve(entry.normalized_table, strict=strict)
            if not table:
                raise ValueError(f"unknown source table '{entry.table_key}'")
            target = lookup.resolve(entry.normalized_reference_table, strict=strict)
            if strict and not target:
                raise ValueError(f"unknown target table '{entry.reference_table_key}'")
            if not target:
                _record(
                    failures,
                    config_source,
                    f"unknown target table '{entry.reference_table_key}'",
                )
            local = _resolve_columns(table, entry.local_columns, strict=strict)
            remote = (
                _resolve_columns(target, entry.reference_columns, strict=strict)
                if target
                else entry.reference_columns
            )
            target_name = target.name if target else entry.normalized_reference_table
            if any(
                fk.columns == local
                and fk.ref_table == target_name
                and fk.ref_columns == remote
                for fk in table.foreign_keys
            ):
                continue
            table.add_foreign_key(ForeignKey(local, target_name, remote))
        except ValueError as exc:
            _record(failures, config_source, str(exc))
