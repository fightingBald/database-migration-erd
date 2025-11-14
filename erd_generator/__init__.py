"""ERD generation toolkit with lazy attribute access to avoid heavy imports."""
from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "main",
    "build_drawio",
    "load_schema_from_migrations",
    "get_last_parse_failures",
    "ParseFailure",
]

from erd_generator.cli import main
from erd_generator.drawio import build_drawio
from erd_generator.sql_parser import load_schema_from_migrations, get_last_parse_failures, ParseFailure


def __getattr__(name: str) -> Any:  # pragma: no cover - thin lazy loader
    if name == "main":
        return import_module("erd_generator.cli").main
    if name == "build_drawio":
        return import_module("erd_generator.drawio").build_drawio
    if name == "load_schema_from_migrations":
        return import_module("erd_generator.sql_parser").load_schema_from_migrations
    if name == "get_last_parse_failures":
        return import_module("erd_generator.sql_parser").get_last_parse_failures
    if name == "ParseFailure":
        return import_module("erd_generator.sql_parser").ParseFailure
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
