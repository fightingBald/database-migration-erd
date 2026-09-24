"""Compare bounded native layouts without sacrificing the existing winner."""

import logging
import tempfile
from pathlib import Path

from .artifacts import write_text_atomic
from .d2 import build_d2
from .d2_affinity import group_weights
from .d2_business import plan_groups
from .d2_geometry import (
    improves_affinity,
    improves_layout,
    improves_packing,
    measure_layout,
)
from .d2_renderer import D2RenderConfig, D2RenderError, render_d2
from .layout_config import LayoutConfig
from .schema import Schema
from .validation import validate_schema

LOGGER = logging.getLogger(__name__)


def _has_affinity(schema: Schema, config: LayoutConfig | None) -> bool:
    relationships = validate_schema(schema).relationships
    groups = plan_groups(schema, relationships, config=config)
    weights = group_weights({n: g.key for g in groups for n in g.tables}, relationships)
    return len(weights) >= 2


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
    show_indexes: bool = True,
) -> str:
    """The caller writes the baseline source first, retaining it on render failure.

    Source-only generation stays pure. SVG generation may select a simpler D2
    hierarchy; the selected source accompanies the native table/FK layout with
    index captions aligned by the renderer.
    """
    source, output = Path(source_path).resolve(), Path(output_path).resolve()
    if source == output or output.suffix.lower() != ".svg":
        raise D2RenderError("D2 output must be a separate .svg file")
    config = config or D2RenderConfig()
    original = source.read_text(encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    options = dict(
        show_types=show_types,
        grouping=grouping,
        layout_config=layout_config,
        show_indexes=show_indexes,
    )
    selected, winning_source = "balanced", original
    with tempfile.TemporaryDirectory(
        prefix=".erd-layout-", dir=output.parent
    ) as temporary:
        folder = Path(temporary)
        winner = folder / "baseline.svg"
        render_d2(source, winner, config)
        eligible = (
            len(schema) >= 12 and grouping == "auto" and not config.force_appendix
        )
        affinity = eligible and _has_affinity(schema, layout_config)
        compact = eligible and config.layout_engine == "elk"
        quality = None
        if compact or affinity:
            try:
                quality = measure_layout(winner, schema, **options)
            except D2RenderError as exc:
                LOGGER.warning(
                    "D2 layout: baseline metrics unavailable; keeping baseline (%s)",
                    exc,
                )
                compact = affinity = False

        attempted = {original}

        def attempt(strategy, mode="none", cluster_sizes=None):
            candidate = build_d2(
                schema,
                direction=direction,
                style=style,
                layout_strategy=strategy,
                cluster_affinity=mode,
                layout_engine=config.layout_engine,
                show_references=show_references,
                **({"cluster_sizes": cluster_sizes} if cluster_sizes else {}),
                **options,
            )
            if candidate in attempted:
                return None
            attempted.add(candidate)
            trial = folder / f"{strategy}-{mode}.d2"
            image = trial.with_suffix(".svg")
            try:
                trial.write_text(candidate, encoding="utf-8")
                render_d2(trial, image, config)
                metrics = measure_layout(image, schema, **options)
            except (D2RenderError, OSError) as exc:
                LOGGER.warning(
                    "D2 layout: %s-%s candidate failed (%s); keeping previous layout",
                    strategy,
                    mode,
                    type(exc).__name__,
                )
                return None
            return image, candidate, metrics

        if compact and (quality.table_area / quality.area < 0.18 or quality.aspect > 2):
            trial = attempt("compact")
            if trial is not None and improves_layout(trial[2], quality):
                LOGGER.info(
                    "D2 layout: compact selected area=-%.1f%%",
                    100 * (1 - trial[2].area / quality.area),
                )
                winner, winning_source, quality = trial
                selected = "compact"
            else:
                LOGGER.info(
                    "D2 layout: compact did not improve quality; keeping baseline"
                )

        # Fix the reference after the old compact step. Candidate tolerances
        # must never accumulate, or a series of improvements could regress it.
        reference = quality
        strategy = selected
        if affinity:
            for mode in ("ordered", "paired"):
                trial = attempt(strategy, mode)
                if trial is None:
                    continue
                metrics = trial[2]
                if not improves_affinity(metrics, reference):
                    LOGGER.info(
                        "D2 layout: %s-%s did not improve proximity safely",
                        strategy,
                        mode,
                    )
                    continue
                if (
                    quality is not reference
                    and metrics.affinity_distance >= quality.affinity_distance
                ):
                    continue
                winner, winning_source, quality = trial
                selected = f"{strategy}-{mode}"
            if quality is not reference:
                LOGGER.info(
                    "D2 layout: %s selected cluster-distance=-%.1f%%",
                    selected,
                    100 * (1 - quality.affinity_distance / reference.affinity_distance),
                )
        if affinity and config.layout_engine == "elk" and len(quality.group_sizes) >= 3:
            # Second-level planning uses the actual sizes of the old winner's
            # clusters. No grids or synthetic relations cross field boundaries.
            trial = attempt(
                strategy,
                "packed",
                {key: (width, height) for key, width, height in quality.group_sizes},
            )
            if (
                trial is not None
                and improves_packing(trial[2], quality)
                and improves_packing(trial[2], reference)
            ):
                LOGGER.info(
                    "D2 layout: measured cluster packing selected area=-%.1f%%",
                    100 * (1 - trial[2].area / quality.area),
                )
                winner, winning_source, quality = trial
                selected = f"{strategy}-packed"
            else:
                LOGGER.info(
                    "D2 layout: measured cluster packing did not improve quality; "
                    "keeping previous layout"
                )
        if winning_source != original:
            write_text_atomic(source, winning_source)
        winner.replace(output)
    return selected
