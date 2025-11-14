"""Command line entry-point for generating draw.io ER diagrams."""
from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional

from .drawio import build_drawio
from .fk_config import apply_foreign_key_config, load_foreign_key_config
from .layout import LayoutConfig
from .sql_parser import ParseFailure, get_last_parse_failures, load_schema_from_migrations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate draw.io ERD from migration SQL files")
    parser.add_argument("--migrations", required=True, help="Path to the root of migration SQL files")
    parser.add_argument("--out", required=True, help="Path to the output .drawio file")
    parser.add_argument("--show-types", action="store_true", help="Append column types to labels")
    parser.add_argument(
        "--per-row",
        type=int,
        default=0,
        help="Tables per row (0 = auto based on graph, default: 0)",
    )
    parser.add_argument(
        "--log-dir",
        help="Optional root directory for parse logs; logs will be written under <log-dir>/parse_log "
        "(default: ./parse_log relative to the current working directory).",
    )
    parser.add_argument(
        "--fk-config",
        help="Optional YAML file describing additional foreign key links to inject before rendering.",
    )
    parser.add_argument(
        "--layout",
        choices=["grid", "graphviz"],
        default="grid",
        help="Layout algorithm to position tables (default: grid).",
    )
    parser.add_argument(
        "--graphviz-prog",
        default="dot",
        help="Graphviz engine to use when --layout graphviz (default: dot).",
    )
    parser.add_argument(
        "--graphviz-scale",
        type=float,
        default=1.0,
        help="Scale factor applied to Graphviz coordinates; increase for more spacing (default: 1.0).",
    )
    parser.add_argument(
        "--graphviz-spacing",
        type=float,
        default=200.0,
        help="Additional uniform spacing (in draw.io units) added to Graphviz coordinates to reduce overlap (default: 200).",
    )
    return parser


def _print_failure_summary(failures: list[ParseFailure]) -> None:
    if not failures:
        return
    print("\nUnsupported SQL statements:")
    for failure in failures:
        location = failure.source or "<input>"
        print(f" - {location}: {failure.reason}: {failure.sql}")


def _resolve_log_directory(log_root: Optional[str]) -> Path:
    base = Path(log_root).expanduser().resolve() if log_root else Path.cwd()
    target_dir = base / "parse_log"
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def _write_failure_log(failures: list[ParseFailure], log_root: Optional[str]) -> None:
    if not failures:
        return
    directory = _resolve_log_directory(log_root)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = directory / f"parse_failures_{timestamp}.log"

    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(f"Parse failures collected at {datetime.now().isoformat()}\n\n")
        for failure in failures:
            location = failure.source or "<input>"
            handle.write(f"{location}\n  {failure.reason}: {failure.sql}\n")

    print(f"Parse log written to {log_path}")

def run_cli(args: argparse.Namespace) -> int:
    schema = load_schema_from_migrations(args.migrations)
    failures = get_last_parse_failures()
    config_entries, config_source = load_foreign_key_config(args.fk_config, failures)
    apply_foreign_key_config(schema, config_entries, config_source=config_source)
    if not schema:
        print("No tables detected. Check your migration path or SQL dialect support.", file=sys.stderr)
        return 1

    layout_config = LayoutConfig(
        per_row=args.per_row,
        layout_algorithm=args.layout,
        graphviz_prog=args.graphviz_prog,
        graphviz_scale=args.graphviz_scale,
        graphviz_spacing=args.graphviz_spacing,
    )
    tree = build_drawio(schema, show_types=args.show_types, layout_config=layout_config)

    try:
        ET.indent(tree, space="  ")  # type: ignore[attr-defined]
    except AttributeError:
        pass

    output_dir = os.path.dirname(os.path.abspath(args.out))
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    tree.write(args.out, encoding="utf-8", xml_declaration=False)
    print(f"Diagram written to {args.out}")

    _print_failure_summary(failures)
    _write_failure_log(failures, args.log_dir)

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_cli(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
