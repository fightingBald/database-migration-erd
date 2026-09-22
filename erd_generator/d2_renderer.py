"""Run the pinned D2 CLI with the selected engine and verify SVG publication."""

import logging
import math
import os
import re
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .d2_engines import engine_flags, validate_layout_engine
from .d2_index_svg import align_index_captions

D2_VERSION = "0.7.1"
LOGGER = logging.getLogger(__name__)


class D2RenderError(RuntimeError):
    """An external rendering or artifact publication failure."""


@dataclass(frozen=True)
class D2RenderConfig:
    executable: str = "d2"
    timeout: float = 120
    force_appendix: bool = False
    layout_engine: str = "elk"

    def __post_init__(self) -> None:
        validate_layout_engine(self.layout_engine)
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("D2 timeout must be finite and positive")
        if not self.executable:
            raise ValueError("D2 executable must not be empty")


def _run(arguments: list[str], config: D2RenderConfig, stage: str) -> str:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("D2_", "ELK_", "TALA_"))
    }
    try:
        result = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            check=True,
            timeout=config.timeout,
            env=env,
        )
    except FileNotFoundError as exc:
        raise D2RenderError(
            f"D2 executable not found: {config.executable}; install D2 {D2_VERSION} or generate source without --render"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise D2RenderError(
            f"D2 {stage} timed out after {config.timeout:g}s (required version {D2_VERSION})"
        ) from exc
    except subprocess.CalledProcessError as exc:
        if stage == "TALA check":
            raise D2RenderError(
                "D2 TALA check failed: install d2plugin-tala on PATH and verify with 'd2 layout tala'"
            ) from exc
        # Compiler stderr may echo SQL-derived labels. Expose positions, not payloads.
        positions = re.findall(r":(\d+):(\d+):", exc.stderr or "")
        location = (
            f" at line {positions[0][0]}, column {positions[0][1]}" if positions else ""
        )
        raise D2RenderError(
            f"D2 {stage} failed with exit {exc.returncode}{location} (required version {D2_VERSION}); inspect the retained .d2 source"
        ) from exc
    except OSError as exc:
        raise D2RenderError(
            f"D2 {stage} could not execute: {exc.strerror or type(exc).__name__}"
        ) from exc
    return result.stdout.strip()


def render_d2(
    source_path: Path, output_path: Path, config: D2RenderConfig | None = None
) -> None:
    config = config or D2RenderConfig()
    source, output = Path(source_path).resolve(), Path(output_path).resolve()
    if source == output or output.suffix.lower() != ".svg":
        raise D2RenderError("D2 output must be a separate .svg file")
    if not source.is_file():
        raise D2RenderError(f"D2 source does not exist: {source}")
    started = time.monotonic()
    version = _run([config.executable, "--version"], config, "version check")
    if version.removeprefix("v") != D2_VERSION:
        raise D2RenderError(
            f"D2 version mismatch: expected {D2_VERSION}, got {version[:80]!r}"
        )
    engine = config.layout_engine
    layout = _run(
        [config.executable, "layout", engine], config, f"{engine.upper()} check"
    )
    if engine == "elk" and not re.match(r"elk\s+\(bundled\):", layout):
        raise D2RenderError("D2 ELK check failed: bundled ELK is unavailable")
    if engine == "tala" and not re.match(r"tala\s+\(", layout):
        raise D2RenderError(
            "D2 TALA check failed: d2plugin-tala was not recognized; verify with 'd2 layout tala'"
        )
    temporary = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=output.parent, prefix=f".{output.stem}.", suffix=".svg", delete=False
        ) as handle:
            temporary = Path(handle.name)
        _run(
            [
                config.executable,
                "--layout",
                engine,
                *engine_flags(engine),
                "--watch=false",
                "--theme=0",
                "--dark-theme=-1",
                "--sketch=false",
                "--scale=-1",
                "--pad=100",
                f"--force-appendix={str(config.force_appendix).lower()}",
                "--timeout",
                str(math.ceil(config.timeout)),
                str(source),
                str(temporary),
            ],
            config,
            "render",
        )
        try:
            root = ET.parse(temporary).getroot()
        except ET.ParseError as exc:
            raise D2RenderError(
                "D2 SVG verification failed: output is not valid XML"
            ) from exc
        if root.tag != "{http://www.w3.org/2000/svg}svg":
            raise D2RenderError(
                "D2 SVG verification failed: output is not an SVG document"
            )
        try:
            svg = temporary.read_text(encoding="utf-8")
            aligned = align_index_captions(svg)
        except ValueError as exc:
            raise D2RenderError(
                "D2 SVG verification failed: index footer alignment"
            ) from exc
        if aligned != svg:
            temporary.write_text(aligned, encoding="utf-8")
        temporary.replace(output)
    except OSError as exc:
        raise D2RenderError(
            f"D2 SVG output failed: {exc.strerror or type(exc).__name__}"
        ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    LOGGER.info(
        "D2 render: version=%s layout=%s elapsed=%.3fs output=%s",
        version,
        engine,
        time.monotonic() - started,
        output,
    )
