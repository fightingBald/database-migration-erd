"""Helpers for loading and applying foreign-key overrides from YAML."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Tuple

from .schema import ForeignKey, Schema, Table
from .sql_parser import ParseFailure


@dataclass(frozen=True)
class ForeignKeyConfigEntry:
    table_key: str
    normalized_table: str
    local_columns: Tuple[str, ...]
    reference_table_key: str
    normalized_reference_table: str
    reference_columns: Tuple[str, ...]


def _normalize_identifier(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    return text.lower()


def _normalize_column_sequence(value: Any) -> Optional[Tuple[str, ...]]:
    if isinstance(value, str):
        return (_normalize_identifier(value),)
    if isinstance(value, (list, tuple)):
        items: list[str] = []
        for item in value:
            if not isinstance(item, str):
                return None
            items.append(_normalize_identifier(item))
        return tuple(items)
    return None


def _record_config_failure(
    failures: Optional[list[ParseFailure]],
    source: str,
    reason: str,
    detail: str,
) -> None:
    print(f"[WARN] {reason} in {source}: {detail}")
    if failures is not None:
        failures.append(ParseFailure(source=source, sql=detail, reason=reason))


def _warn(source: Optional[str], message: str) -> None:
    prefix = f"[WARN] Foreign key config{f' {source}' if source else ''}"
    print(f"{prefix}: {message}")


def load_foreign_key_config(
    config_path: Optional[str],
    failures: Optional[list[ParseFailure]],
) -> tuple[list[ForeignKeyConfigEntry], Optional[str]]:
    if not config_path:
        return [], None
    path = Path(config_path).expanduser()
    source = str(path)
    if not path.exists():
        _record_config_failure(
            failures,
            source,
            "Foreign key config missing",
            "File not found",
        )
        return [], source
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        _record_config_failure(
            failures,
            source,
            "Foreign key config error",
            "PyYAML is not installed",
        )
        return [], source
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw_config = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        _record_config_failure(
            failures,
            source,
            "Foreign key config parse error",
            str(exc),
        )
        return [], source
    except OSError as exc:
        _record_config_failure(
            failures,
            source,
            "Foreign key config error",
            str(exc),
        )
        return [], source
    if raw_config is None:
        return [], source
    if not isinstance(raw_config, dict):
        _record_config_failure(
            failures,
            source,
            "Foreign key config error",
            "Top-level YAML must be a mapping of table names.",
        )
        return [], source

    entries: list[ForeignKeyConfigEntry] = []
    for raw_table_name, payload in raw_config.items():
        if not isinstance(raw_table_name, str):
            _warn(source, f"table name must be a string (got {type(raw_table_name).__name__}); skipping.")
            continue
        normalized_table = _normalize_identifier(raw_table_name)
        fk_entries: Iterable[Any]
        if isinstance(payload, dict):
            fk_entries = payload.get("fks") or []
        elif isinstance(payload, (list, tuple)):
            fk_entries = payload
        else:
            _warn(
                source,
                f"entry for table '{raw_table_name}' must be a mapping or sequence; skipping.",
            )
            continue
        for entry in fk_entries:
            local_spec: Any
            reference_table_spec: Any
            reference_columns_spec: Any = ()
            if isinstance(entry, dict):
                local_spec = entry.get("columns") or entry.get("local") or entry.get("source")
                reference_table_spec = entry.get("table") or entry.get("ref_table") or entry.get("references")
                reference_columns_spec = (
                    entry.get("ref_columns")
                    or entry.get("target")
                    or entry.get("targets")
                    or entry.get("columns_ref")
                )
            elif isinstance(entry, (list, tuple)):
                if len(entry) < 2:
                    _warn(
                        source,
                        f"entry for table '{raw_table_name}' expects at least two items; got {entry!r}.",
                    )
                    continue
                local_spec = entry[0]
                reference_table_spec = entry[1]
                if len(entry) > 2:
                    reference_columns_spec = entry[2]
            else:
                _warn(
                    source,
                    f"entry for table '{raw_table_name}' must be a mapping or sequence; got {type(entry).__name__}.",
                )
                continue

            local_columns = _normalize_column_sequence(local_spec)
            if not local_columns:
                _warn(
                    source,
                    f"entry for table '{raw_table_name}' has invalid local columns: {entry!r}.",
                )
                continue
            if not isinstance(reference_table_spec, str) or not reference_table_spec.strip():
                _warn(
                    source,
                    f"entry for table '{raw_table_name}' is missing a reference table: {entry!r}.",
                )
                continue
            normalized_reference_table = _normalize_identifier(reference_table_spec)
            reference_columns = (
                _normalize_column_sequence(reference_columns_spec) if reference_columns_spec else local_columns
            )
            if not reference_columns or len(reference_columns) != len(local_columns):
                _warn(
                    source,
                    f"entry for table '{raw_table_name}' has mismatched column counts "
                    f"{local_columns} -> {reference_columns}; skipping.",
                )
                continue
            entries.append(
                ForeignKeyConfigEntry(
                    table_key=raw_table_name,
                    normalized_table=normalized_table,
                    local_columns=local_columns,
                    reference_table_key=reference_table_spec,
                    normalized_reference_table=normalized_reference_table,
                    reference_columns=reference_columns,
                )
            )
    return entries, source


class _SchemaLookup:
    def __init__(self, schema: Schema) -> None:
        self._direct: dict[str, Table] = {}
        self._suffix: dict[str, Table] = {}
        for name, table in schema.items():
            lowered = name.lower()
            self._direct[lowered] = table
            suffix = lowered.rsplit(".", 1)[-1]
            self._suffix.setdefault(suffix, table)

    def resolve(self, identifier: str) -> Optional[Table]:
        if not identifier:
            return None
        normalized = identifier.lower()
        table = self._direct.get(normalized)
        if table:
            return table
        suffix = normalized.rsplit(".", 1)[-1]
        return self._suffix.get(suffix)


def _resolve_columns(table: Table, columns: Iterable[str]) -> tuple[str, ...]:
    resolved: list[str] = []
    for column_name in columns:
        column = table.get_column(column_name)
        resolved.append(column.name if column else column_name)
    return tuple(resolved)


def _foreign_key_exists(table: Table, candidate: ForeignKey) -> bool:
    return any(
        fk.columns == candidate.columns
        and fk.ref_table == candidate.ref_table
        and fk.ref_columns == candidate.ref_columns
        for fk in table.foreign_keys
    )


def apply_foreign_key_config(
    schema: Schema,
    entries: Iterable[ForeignKeyConfigEntry],
    *,
    config_source: Optional[str] = None,
) -> None:
    lookup = _SchemaLookup(schema)
    for entry in entries:
        table = lookup.resolve(entry.normalized_table)
        if not table:
            _warn(
                config_source,
                f"references unknown table '{entry.table_key}'; skipping.",
            )
            continue
        target_table = lookup.resolve(entry.normalized_reference_table)
        if not target_table:
            _warn(
                config_source,
                f"references unknown target table '{entry.reference_table_key}' from '{entry.table_key}'.",
            )

        local_columns = _resolve_columns(table, entry.local_columns)
        if target_table:
            reference_columns = _resolve_columns(target_table, entry.reference_columns)
            reference_table_name = target_table.name
        else:
            reference_columns = entry.reference_columns
            reference_table_name = entry.normalized_reference_table

        candidate = ForeignKey(
            columns=local_columns,
            ref_table=reference_table_name,
            ref_columns=reference_columns,
        )
        if _foreign_key_exists(table, candidate):
            continue
        table.add_foreign_key(candidate)
