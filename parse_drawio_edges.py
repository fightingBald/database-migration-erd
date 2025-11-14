#!/usr/bin/env python3
"""CLI to extract table/column edge mappings from a draw.io XML file."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from erd_generator.drawio_parser import parse_drawio_edges


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse a draw.io (.drawio) XML file and emit table/column edges as JSON."
    )
    parser.add_argument(
        "drawio_file",
        type=Path,
        help="Path to the .drawio XML file to parse",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation (default: 2, set to 0 for compact output)",
    )
    args = parser.parse_args()

    if not args.drawio_file.exists():
        parser.error(f"File not found: {args.drawio_file}")

    edges = parse_drawio_edges(str(args.drawio_file))
    indent = None if args.indent <= 0 else args.indent
    json.dump(edges, sys.stdout, ensure_ascii=False, indent=indent)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
