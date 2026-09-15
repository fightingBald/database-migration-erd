"""CLI orchestration with a D2 module entrypoint and compatible draw.io defaults."""

from __future__ import annotations

import argparse
import logging
import math
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


def build_parser(*, default_format: str = "drawio") -> argparse.ArgumentParser:
    positional_io = default_format == "d2"
    parser = argparse.ArgumentParser(
        description="Generate D2/ELK or draw.io ERDs from migration SQL",
        allow_abbrev=False,
        usage="%(prog)s SQL_DIR OUTPUT [options]" if positional_io else None,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s ./db/migration ./generated/schema.svg\n"
            "  %(prog)s ./db/migration ./generated/schema.d2\n\n"
            "SVG output also writes same-stem D2 source. D2 output alone does not\n"
            "require the D2 executable. Short-form defaults: types shown, clean\n"
            "style, ELK layout. --migrations/--out remain supported."
        )
        if positional_io
        else None,
    )
    if positional_io:
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
        required=not positional_io,
        help="Named input directory; use together with --out",
    )
    parser.add_argument(
        "--out",
        required=not positional_io,
        help="Named output path; use together with --migrations",
    )
    parser.add_argument(
        "--format",
        choices=["d2", "drawio"],
        default=default_format,
        help=f"Output backend (default: {default_format})",
    )
    types = parser.add_mutually_exclusive_group()
    types.add_argument(
        "--show-types",
        action="store_true",
        default=None if positional_io else False,
        help="Include column data types (default with SQL_DIR OUTPUT)",
    )
    if positional_io:
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
    parser.add_argument(
        "--layout",
        choices=["elk", "grid", "graphviz"],
        help="D2: elk; draw.io: grid (default) or graphviz",
    )
    d2 = parser.add_argument_group("D2 options")
    d2.add_argument(
        "--style",
        choices=STYLES,
        help="D2 visual style: clean (default) or classic",
    )
    d2.add_argument(
        "--direction",
        choices=["right", "left", "up", "down"],
        help="D2 diagram direction (default: right)",
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
    legacy = parser.add_argument_group("draw.io layout options")
    legacy.add_argument(
        "--per-row", type=int, help="Tables per grid row (default: 0, automatic)"
    )
    legacy.add_argument("--graphviz-prog", help="Graphviz engine (default: dot)")
    legacy.add_argument(
        "--graphviz-scale", type=float, help="Graphviz coordinate scale (default: 1)"
    )
    legacy.add_argument(
        "--graphviz-spacing", type=float, help="Extra Graphviz spacing (default: 200)"
    )
    return parser


def _resolve_arguments(args: argparse.Namespace) -> None:
    sql_dir = getattr(args, "sql_dir", None)
    output_path = getattr(args, "output_path", None)
    positional_io = sql_dir is not None or output_path is not None
    if positional_io:
        if args.migrations is not None or args.out is not None:
            raise ValueError(
                "use SQL_DIR OUTPUT or --migrations/--out, without mixing the two forms"
            )
        if sql_dir is None or output_path is None:
            raise ValueError("both SQL_DIR and OUTPUT are required")
        if args.format != "d2":
            raise ValueError("SQL_DIR OUTPUT is only supported for D2")
        args.migrations, args.out = sql_dir, output_path
    elif args.migrations is None or args.out is None:
        raise ValueError("provide SQL_DIR OUTPUT or both --migrations and --out")
    if args.show_types is None:
        # Keep the named command's historical default while making the short
        # command useful without an extra --show-types flag.
        args.show_types = positional_io


def _validate_options(args: argparse.Namespace) -> None:
    suffix = Path(args.out).suffix.lower()
    if args.format == "d2":
        if suffix not in (".d2", ".svg"):
            raise ValueError("D2 output must use .svg for an image or .d2 for source")
        if suffix == ".svg":
            args.render = "svg"
        if args.layout not in (None, "elk"):
            raise ValueError("D2 requires --layout elk")
        if any(
            getattr(args, name) is not None
            for name in (
                "per_row",
                "graphviz_prog",
                "graphviz_scale",
                "graphviz_spacing",
            )
        ):
            raise ValueError("--per-row and --graphviz-* are draw.io options")
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
    else:
        if suffix not in (".drawio", ".xml"):
            raise ValueError("draw.io output must use .drawio or .xml")
        if args.layout not in (None, "grid", "graphviz"):
            raise ValueError("draw.io supports only grid or graphviz layouts")
        if (
            args.style is not None
            or args.direction
            or args.render
            or args.d2_binary is not None
            or args.render_timeout is not None
            or args.force_appendix
        ):
            raise ValueError(
                "D2 style/direction/rendering options are not applicable to draw.io"
            )
        for name in ("graphviz_scale", "graphviz_spacing"):
            value = getattr(args, name)
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and nonnegative")


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


def _write_drawio(args: argparse.Namespace, schema: dict, output: Path) -> None:
    import xml.etree.ElementTree as ET

    from .drawio import build_drawio
    from .layout import LayoutConfig

    config = LayoutConfig(
        per_row=args.per_row if args.per_row is not None else 0,
        layout_algorithm=args.layout or "grid",
        graphviz_prog=args.graphviz_prog or "dot",
        graphviz_scale=args.graphviz_scale if args.graphviz_scale is not None else 1.0,
        graphviz_spacing=args.graphviz_spacing
        if args.graphviz_spacing is not None
        else 200.0,
    )
    tree = build_drawio(schema, show_types=args.show_types, layout_config=config)
    ET.indent(tree, space="  ")
    _write_source(output, ET.tostring(tree.getroot(), encoding="unicode"))


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
            strict=args.format == "d2",
        )
        _write_failure_log(failures, args.log_dir)
        if args.format == "d2" and any(f.severity == "error" for f in failures):
            raise ValueError(
                "schema loading failed; resolve the reported SQL/configuration diagnostics before generating D2"
            )
        if not schema:
            raise ValueError(
                "no tables detected; check migration input and SQL support"
            )
        output = Path(args.out).expanduser().resolve()
        if args.format == "d2":
            from .d2 import build_d2

            source_output = (
                output.with_suffix(".d2") if output.suffix.lower() == ".svg" else output
            )
            svg_output = (
                output
                if output.suffix.lower() == ".svg"
                else output.with_suffix(".svg")
            )
            source = build_d2(
                schema,
                show_types=args.show_types,
                direction=args.direction or "right",
                style=args.style or "clean",
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
        else:
            _write_drawio(args, schema, output)
        LOGGER.info(
            "ERD generated: format=%s tables=%d columns=%d foreign_keys=%d",
            args.format,
            len(schema),
            sum(len(t.columns) for t in schema.values()),
            sum(len(t.foreign_keys) for t in schema.values()),
        )
        print(f"Diagram written to {written_source or output}")
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


def main(argv: list[str] | None = None, *, default_format: str = "drawio") -> int:
    parser = build_parser(default_format=default_format)
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
