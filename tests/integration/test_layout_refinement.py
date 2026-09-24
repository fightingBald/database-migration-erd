"""Exercise bounded refinement through real ELK, including preserved row ports."""

import xml.etree.ElementTree as ET

import pytest

from erd_generator import d2_refinement
from erd_generator.d2 import build_d2
from erd_generator.d2_geometry import (
    improves_affinity,
    improves_layout,
    improves_packing,
    improves_partitioned,
    measure_svg,
)
from erd_generator.d2_renderer import render_source
from erd_generator.validation import validate_schema
from tests.support.schemas import business_schema, scenario
from tests.support.svg import (
    assert_fk_arrows,
    assert_named_regions,
    assert_no_overlaps,
    table_boxes,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "shape", ["isolated", "chain", "star", "communities", "composite_cycles"]
)
def test_refinement_cannot_regress_other_graph_shapes(tmp_path, monkeypatch, shape):
    schema = scenario(shape)
    verify_refinement(schema, tmp_path, monkeypatch)


@pytest.mark.parametrize("direction", ["left", "up", "down"])
@pytest.mark.parametrize("style", ["clean", "classic"])
def test_refinement_preserves_composite_cycles_in_other_directions(
    tmp_path, monkeypatch, direction, style
):
    verify_refinement(
        business_schema(), tmp_path, monkeypatch, direction=direction, style=style
    )


def test_refinement_keeps_native_source_reference_labels(tmp_path, monkeypatch):
    verify_refinement(business_schema(), tmp_path, monkeypatch, show_references=True)


def verify_refinement(
    schema,
    tmp_path,
    monkeypatch,
    direction="right",
    style="clean",
    show_references=False,
):
    source, image = tmp_path / "schema.d2", tmp_path / "schema.svg"
    options = dict(
        show_types=True,
        direction=direction,
        style=style,
        show_references=show_references,
    )
    original = build_d2(schema, **options)
    source.write_text(original)
    measurements, native = {}, {}

    def spy(content, config):
        svg = render_source(content, config)
        root = ET.fromstring(svg)
        boxes = table_boxes(root)
        assert set(boxes) == set(schema)
        assert_no_overlaps(boxes)
        assert_named_regions(root, schema)
        native[content] = svg
        if "_erd_partition_0: {" in content:
            return svg  # Boundary arrows are added by composition, not D2.
        assert_fk_arrows(schema, root)
        if show_references:
            labels = [
                "".join(t.itertext())
                for t in root.iter("{http://www.w3.org/2000/svg}text")
            ]
            assert sum("FK →" in label for label in labels) == 6
        measurements[content] = measure_svg(svg, schema, show_types=True)
        return svg

    monkeypatch.setattr(d2_refinement, "render_source", spy)
    selected = d2_refinement.render_optimized(
        schema, original, image, source_output=source, **options
    )
    winner = source.read_text()
    if selected == "partitioned":
        assert winner == original
        actual = measure_svg(image.read_text(), schema, show_types=True)
        assert improves_partitioned(
            actual,
            measurements[original],
            sum(len(f.columns) for f in validate_schema(schema).relationships),
        )
        root = ET.fromstring(image.read_text())
        assert_fk_arrows(schema, root)
        assert_no_overlaps(table_boxes(root))
        assert_named_regions(root, schema)
        assert len(native) == 2
        assert set(tmp_path.iterdir()) == {source, image}
        return
    assert image.read_text() == native[winner]
    assert 1 <= len(native) <= 6
    compact = build_d2(schema, **options, layout_strategy="compact")
    previous = (
        compact
        if compact in measurements
        and improves_layout(measurements[compact], measurements[original])
        else original
    )
    if selected.endswith("-packed"):
        previous_candidates = [
            content
            for content in measurements
            if content != winner
            and improves_affinity(measurements[content], measurements[previous])
        ]
        previous = min(
            previous_candidates,
            key=lambda content: measurements[content].affinity_distance,
            default=previous,
        )
        assert improves_packing(measurements[winner], measurements[previous])
        assert winner == build_d2(
            schema,
            **options,
            layout_strategy=selected.removesuffix("-packed"),
            cluster_affinity="packed",
            cluster_sizes={
                key: (w, h) for key, w, h in measurements[previous].group_sizes
            },
        )
    elif selected.endswith(("-ordered", "-paired")):
        assert improves_affinity(measurements[winner], measurements[previous])
        strategy, mode = selected.split("-")
        assert winner == build_d2(
            schema, **options, layout_strategy=strategy, cluster_affinity=mode
        )
    elif selected == "compact":
        assert improves_layout(measurements[winner], measurements[original])
        assert winner == build_d2(schema, **options, layout_strategy="compact")
    else:
        assert winner == original
    assert set(tmp_path.iterdir()) == {source, image}
