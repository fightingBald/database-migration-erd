"""Command line entry-point for generating draw.io ER diagrams."""
from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET

from .drawio import build_drawio
from .layout import LayoutConfig
from .sql_parser import load_schema_from_migrations


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
        "--out-png",
        help="Optional path to a PNG snapshot rendered with a lightweight built-in renderer",
    )
    return parser


def run_cli(args: argparse.Namespace) -> int:
    schema = load_schema_from_migrations(args.migrations)
    if not schema:
        print("No tables detected. Check your migration path or SQL dialect support.", file=sys.stderr)
        return 1

    layout_config = LayoutConfig(per_row=args.per_row)
    tree = build_drawio(schema, show_types=args.show_types, layout_config=layout_config)

    try:
        ET.indent(tree, space="  ")  # type: ignore[attr-defined]
    except AttributeError:
        pass

    xml_string = ET.tostring(tree.getroot(), encoding="utf-8").decode("utf-8")

    output_dir = os.path.dirname(os.path.abspath(args.out))
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    tree.write(args.out, encoding="utf-8", xml_declaration=False)
    print(f"Diagram written to {args.out}")


    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_cli(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
