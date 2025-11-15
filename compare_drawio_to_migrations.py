#!/usr/bin/env python3
"""CLI to compare migration SQL schemas with draw.io documents."""
from __future__ import annotations

from erd_generator.schema_diff import run_diff_cli


def main() -> int:
    return run_diff_cli()


if __name__ == "__main__":
    raise SystemExit(main())
