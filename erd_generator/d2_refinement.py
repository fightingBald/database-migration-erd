"""Compare at most two native ELK layouts and publish the verified winner."""

import logging
from pathlib import Path
import tempfile

from .artifacts import write_text_atomic
from .d2 import build_d2
from .d2_geometry import improves_layout, measure_layout
from .d2_renderer import D2RenderConfig, D2RenderError, render_d2
from .layout_config import LayoutConfig
from .schema import Schema

LOGGER = logging.getLogger(__name__)


def render_optimized(
    schema: Schema,
    source_path: Path,
    output_path: Path,
    config: D2RenderConfig | None = None,
    *,
    show_types: bool = False,
    direction: str = "right",
    style: str = "clean",
    grouping: str = "auto",
    layout_config: LayoutConfig | None = None,
    show_references: bool = False,
) -> str:
    """The caller writes the baseline source first, retaining it on render failure.

    Source-only generation stays pure. SVG generation may select a simpler D2
    hierarchy; the selected source always accompanies its unmodified native SVG.
    """
    source, output = Path(source_path).resolve(), Path(output_path).resolve()
    if source == output or output.suffix.lower() != ".svg":
        raise D2RenderError("D2 output must be a separate .svg file")
    config = config or D2RenderConfig()
    original = source.read_text(encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    options = dict(
        show_types=show_types, grouping=grouping, layout_config=layout_config
    )
    selected = "balanced"
    with tempfile.TemporaryDirectory(
        prefix=".erd-layout-", dir=output.parent
    ) as temporary:
        folder = Path(temporary)
        winner = folder / "baseline.svg"
        render_d2(source, winner, config)
        # Ordinary renders and appendices keep their existing single-pass path.
        eligible = (
            len(schema) >= 12 and grouping == "auto" and not config.force_appendix
        )
        if eligible:
            try:
                baseline = measure_layout(winner, schema, **options)
            except D2RenderError as exc:
                LOGGER.warning(
                    "D2 layout: baseline metrics unavailable; keeping baseline (%s)",
                    exc,
                )
                eligible = False
            else:
                eligible = (
                    baseline.table_area / baseline.area < 0.18 or baseline.aspect > 2
                )
        if eligible:
            candidate = build_d2(
                schema,
                direction=direction,
                style=style,
                layout_strategy="compact",
                show_references=show_references,
                **options,
            )
            if candidate != original:
                trial = folder / "candidate.d2"
                image = trial.with_suffix(".svg")
                try:
                    trial.write_text(candidate, encoding="utf-8")
                    render_d2(trial, image, config)
                    metrics = measure_layout(image, schema, **options)
                except (D2RenderError, OSError) as exc:
                    LOGGER.warning(
                        "D2 layout: candidate failed (%s); keeping baseline",
                        type(exc).__name__,
                    )
                else:
                    if improves_layout(metrics, baseline):
                        write_text_atomic(source, candidate)
                        winner, selected = image, "compact"
                        LOGGER.info(
                            "D2 layout: compact selected area=-%.1f%% longest-side=-%.1f%% routes=-%.1f%%",
                            100 * (1 - metrics.area / baseline.area),
                            100
                            * (
                                1
                                - max(metrics.width, metrics.height)
                                / max(baseline.width, baseline.height)
                            ),
                            100 * (1 - metrics.total_length / baseline.total_length)
                            if baseline.total_length
                            else 0,
                        )
                    else:
                        LOGGER.info(
                            "D2 layout: candidate did not improve quality; keeping baseline"
                        )
        winner.replace(output)
    return selected
