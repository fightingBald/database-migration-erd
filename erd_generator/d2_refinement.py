"""Compare native and independently packed layouts before atomic publication."""

import logging
from pathlib import Path

from .artifacts import write_text_atomic
from .d2 import build_d2, build_partitioned_d2
from .d2_affinity import group_weights
from .d2_business import plan_groups
from .d2_geometry import (
    improves_affinity,
    improves_layout,
    improves_packing,
    improves_partitioned,
    measure_svg,
)
from .d2_renderer import D2RenderConfig, D2RenderError, render_source
from .layout_config import LayoutConfig
from .schema import Schema
from .svg_partitions import compose_partitions
from .validation import validate_schema

LOGGER = logging.getLogger(__name__)


def _has_affinity(schema: Schema, config: LayoutConfig | None) -> bool:
    relationships = validate_schema(schema).relationships
    groups = plan_groups(schema, relationships, config=config)
    weights = group_weights({n: g.key for g in groups for n in g.tables}, relationships)
    return len(weights) >= 2


def render_optimized(
    schema: Schema,
    source: str,
    output_path: Path,
    config: D2RenderConfig | None = None,
    *,
    source_output: Path | None = None,
    show_types: bool = False,
    direction: str = "right",
    style: str = "clean",
    grouping: str = "auto",
    layout_config: LayoutConfig | None = None,
    show_references: bool = False,
    show_indexes: bool = True,
) -> str:
    """Compare source/SVG candidates in memory and atomically publish the winner.

    When source_output is explicit, the caller first saves the baseline source
    for diagnosis. Update that export only after the selected SVG is verified.
    """
    output = Path(output_path).resolve()
    source_output = Path(source_output).resolve() if source_output is not None else None
    if source_output == output or output.suffix.lower() != ".svg":
        raise D2RenderError("D2 output must be a separate .svg file")
    config = config or D2RenderConfig()
    options = dict(
        show_types=show_types,
        grouping=grouping,
        layout_config=layout_config,
        show_indexes=show_indexes,
    )
    selected, winning_source = "balanced", source
    winner = render_source(source, config)
    eligible = len(schema) >= 12 and grouping == "auto" and not config.force_appendix
    affinity = eligible and _has_affinity(schema, layout_config)
    compact = eligible and config.layout_engine == "elk"
    quality = None
    if compact or affinity:
        try:
            quality = measure_svg(winner, schema, **options)
        except D2RenderError as exc:
            LOGGER.warning(
                "D2 layout: baseline metrics unavailable; keeping baseline (%s)",
                exc,
            )
            compact = affinity = False

    # Local layout first, then measured rectangle placement and boundary routing.
    # This fixes external-only leaf families which native hierarchical edges
    # otherwise force into one tall layer. Small/already compact graphs skip it.
    if (
        compact
        and affinity
        and 3 <= len(quality.group_sizes) <= 24
        and (
            quality.aspect > 2
            or quality.table_area / quality.area < 0.18
            or any(max(w, h) > 4 * min(w, h) for _, w, h in quality.group_sizes)
        )
    ):
        try:
            independent = build_partitioned_d2(
                schema,
                show_types=show_types,
                direction=direction,
                style=style,
                layout_config=layout_config,
                show_references=show_references,
                show_indexes=show_indexes,
            )
            composed = compose_partitions(
                render_source(independent, config),
                schema,
                layout_config=layout_config,
                style=style,
            )
            measured = measure_svg(composed, schema, **options)
            arrows = sum(len(f.columns) for f in validate_schema(schema).relationships)
            if improves_partitioned(measured, quality, arrows):
                LOGGER.info(
                    "D2 layout: partitioned selected canvas=%.0fx%.0f -> %.0fx%.0f "
                    "area=-%.1f%% longest-route=-%.1f%% crossing-pairs=%d -> %d "
                    "crossing-points=%d -> %d",
                    quality.width,
                    quality.height,
                    measured.width,
                    measured.height,
                    100 * (1 - measured.area / quality.area),
                    100 * (1 - measured.longest / quality.longest),
                    quality.crossings,
                    measured.crossings,
                    quality.crossing_points,
                    measured.crossing_points,
                )
                write_text_atomic(output, composed)
                return "partitioned"
            LOGGER.info(
                "D2 layout: partitioned rejected area=%+.1f%% longest-route=%+.1f%% "
                "total-routes=%+.1f%% crossings=%d -> %d",
                100 * (measured.area / quality.area - 1),
                100 * (measured.longest / quality.longest - 1),
                100 * (measured.total_length / quality.total_length - 1),
                quality.crossings,
                measured.crossings,
            )
        except (D2RenderError, ValueError) as exc:
            LOGGER.warning(
                "D2 layout: partitioned candidate failed (%s); keeping native layout",
                type(exc).__name__,
            )

    attempted = {source}

    def attempt(strategy, mode="none", cluster_sizes=None):
        candidate = build_d2(
            schema,
            direction=direction,
            style=style,
            layout_strategy=strategy,
            cluster_affinity=mode,
            layout_engine=config.layout_engine,
            show_references=show_references,
            cluster_sizes=cluster_sizes,
            **options,
        )
        if candidate in attempted:
            return None
        attempted.add(candidate)
        try:
            image = render_source(candidate, config)
            metrics = measure_svg(image, schema, **options)
        except D2RenderError as exc:
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
            LOGGER.info("D2 layout: compact did not improve quality; keeping baseline")

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
    if source_output is not None and winning_source != source:
        write_text_atomic(source_output, winning_source)
    write_text_atomic(output, winner)
    return selected
