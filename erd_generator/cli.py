"""Load migration SQL, generate D2 source and optionally render an ELK SVG."""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from .d2_renderer import D2RenderConfig, D2RenderError, render_d2
from .d2_styles import STYLES
from .diagnostics import ParseFailure
from .fk_config import apply_foreign_key_config, load_foreign_key_config
from .sql_parser import load_schema_result

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate D2/ELK ERDs from migration SQL",
        allow_abbrev=False,
        usage="%(prog)s SQL_DIR OUTPUT [options]",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s ./db/migration ./generated/schema.svg\n"
            "  %(prog)s ./db/migration ./generated/schema.d2\n\n"
            "SVG output also writes same-stem D2 source. D2 output alone does not\n"
            "require the D2 executable. Short-form defaults: types shown, clean\n"
            "style, ELK layout. Named paths: --migrations SQL_DIR --out OUTPUT."
        ),
    )
    parser.add_argument(
        "sql_dir",
        nargs="?",
        metavar="SQL_DIR",
        help="Input migration SQL directory",
    )
    parser.add_argument(
        "output_path",
        nargs="?",
        metavar="OUTPUT",
        help="Output .svg image (plus .d2 source), or .d2 source only",
    )
    parser.add_argument(
        "--migrations",
        help="Named input directory; use together with --out",
    )
    parser.add_argument(
        "--out",
        help="Named output path; use together with --migrations",
    )
    types = parser.add_mutually_exclusive_group()
    types.add_argument(
        "--show-types",
        action="store_true",
        default=None,
        help="Include column data types (default with SQL_DIR OUTPUT)",
    )
    types.add_argument(
        "--hide-types",
        dest="show_types",
        action="store_false",
        default=None,
        help="Omit column data types",
    )
    parser.add_argument(
        "--fk-config", help="YAML file containing additional foreign keys"
    )
    parser.add_argument(
        "--log-dir", help="Root for parse_log/ diagnostics (default: working directory)"
    )
    d2 = parser.add_argument_group("D2 options")
    d2.add_argument(
        "--style",
        choices=STYLES,
        default="clean",
        help="D2 visual style: clean (default) or classic",
    )
    d2.add_argument(
        "--direction",
        choices=["right", "left", "up", "down"],
        default="right",
        help="D2 diagram direction (default: right)",
    )
    d2.add_argument(
        "--grouping",
        choices=["auto", "none"],
        default="auto",
        help="Infer business and relationship groups (default: auto)",
    )
    d2.add_argument(
        "--layout-config",
        metavar="PATH",
        help="Optional YAML overrides for business groups, titles and colours",
    )
    d2.add_argument(
        "--render", choices=["svg"], help="Also render a same-stem SVG with ELK"
    )
    d2.add_argument("--d2-binary", help="D2 executable (render only; default: d2)")
    d2.add_argument(
        "--render-timeout",
        type=float,
        help="Seconds per D2 process (render only; default: 120)",
    )
    d2.add_argument(
        "--force-appendix",
        action="store_true",
        help="Show tooltip notes in the SVG appendix (SVG output only)",
    )
    return parser


def _resolve_arguments(args: argparse.Namespace) -> None:
    sql_dir, output_path = args.sql_dir, args.output_path
    positional_io = sql_dir is not None or output_path is not None
    if positional_io:
        if args.migrations is not None or args.out is not None:
            raise ValueError(
                "use SQL_DIR OUTPUT or --migrations/--out, without mixing the two forms"
            )
        if sql_dir is None or output_path is None:
            raise ValueError("both SQL_DIR and OUTPUT are required")
        args.migrations, args.out = sql_dir, output_path
    elif args.migrations is None or args.out is None:
        raise ValueError("provide SQL_DIR OUTPUT or both --migrations and --out")
    if args.show_types is None:
        # Keep the named command's historical default while making the short
        # command useful without an extra --show-types flag.
        args.show_types = positional_io


def _validate_options(args: argparse.Namespace) -> None:
    suffix = Path(args.out).suffix.lower()
    if suffix not in (".d2", ".svg"):
        raise ValueError("D2 output must use .svg for an image or .d2 for source")
    if suffix == ".svg":
        args.render = "svg"
    if not args.render and (
        args.d2_binary is not None
        or args.render_timeout is not None
        or args.force_appendix
    ):
        raise ValueError(
            "D2 executable, timeout and appendix options require .svg output or --render svg"
        )
    if args.render:
        D2RenderConfig(
            executable=args.d2_binary or "d2",
            timeout=args.render_timeout if args.render_timeout is not None else 120,
        )


def _write_failure_log(failures: list[ParseFailure], log_root: str | None) -> None:
    if not failures:
        return
    lines = [f"{failure.location}: {failure.reason}" for failure in failures]
    for line in lines:
        print(line, file=sys.stderr)
    directory = (Path(log_root).expanduser() if log_root else Path.cwd()) / "parse_log"
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"parse_failures_{datetime.now():%Y%m%d-%H%M%S-%f}.log"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Parse diagnostics written to %s", output)


def _write_source(output: Path, text: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_cli(args: argparse.Namespace) -> int:
    written_source: Path | None = None
    try:
        result = load_schema_result(args.migrations)
        schema, failures = result.schema, result.failures
        entries, config_source = load_foreign_key_config(args.fk_config, failures)
        apply_foreign_key_config(
            schema,
            entries,
            config_source=config_source,
            failures=failures,
        )
        _write_failure_log(failures, args.log_dir)
        if any(f.severity == "error" for f in failures):
            raise ValueError(
                "schema loading failed; resolve the reported SQL/configuration diagnostics before generating D2"
            )
        if not schema:
            raise ValueError(
                "no tables detected; check migration input and SQL support"
            )
        output = Path(args.out).expanduser().resolve()
        from .d2 import build_d2
        from .layout_config import load_layout_config

        layout_config = (
            load_layout_config(args.layout_config)
            if args.layout_config is not None
            else None
        )

        source_output = (
            output.with_suffix(".d2") if output.suffix.lower() == ".svg" else output
        )
        svg_output = (
            output if output.suffix.lower() == ".svg" else output.with_suffix(".svg")
        )
        source = build_d2(
            schema,
            show_types=args.show_types,
            direction=args.direction,
            style=args.style,
            grouping=args.grouping,
            layout_config=layout_config,
        )
        LOGGER.info(
            "D2 layout: grouping=%s layout_overrides=%d",
            args.grouping,
            len(layout_config.groups) if layout_config else 0,
        )
        _write_source(source_output, source)
        written_source = source_output
        if args.render:
            render_d2(
                source_output,
                svg_output,
                D2RenderConfig(
                    executable=args.d2_binary or "d2",
                    timeout=args.render_timeout
                    if args.render_timeout is not None
                    else 120,
                    force_appendix=args.force_appendix,
                ),
            )
        LOGGER.info(
            "ERD generated: tables=%d columns=%d foreign_keys=%d",
            len(schema),
            sum(len(t.columns) for t in schema.values()),
            sum(len(t.foreign_keys) for t in schema.values()),
        )
        print(f"Diagram written to {source_output}")
        if args.render:
            print(f"SVG written to {svg_output}")
        return 0
    except (ValueError, OSError, D2RenderError) as exc:
        message = (
            "input is not valid UTF-8" if isinstance(exc, UnicodeError) else str(exc)
        )
        print(f"ERD generation failed: {message}", file=sys.stderr)
        if written_source is not None and args.render:
            print(
                f"D2 source retained at {written_source}; SVG was not updated.",
                file=sys.stderr,
            )
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _resolve_arguments(args)
        _validate_options(args)
    except ValueError as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    # sqlglot fallback warnings echo source SQL; our diagnostics report file/reason instead.
    logging.getLogger("sqlglot").setLevel(logging.ERROR)
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
