"""Exercise bounded refinement through real ELK, including preserved row ports."""

import xml.etree.ElementTree as ET

import pytest

from erd_generator import d2_refinement
from erd_generator.d2 import build_d2
from erd_generator.d2_geometry import improves_affinity, improves_layout, measure_layout
from erd_generator.d2_renderer import render_d2
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

    def spy(path, target, config):
        render_d2(path, target, config)
        content = path.read_text()
        root = ET.parse(target).getroot()
        boxes = table_boxes(root)
        assert set(boxes) == set(schema)
        assert_no_overlaps(boxes)
        assert_fk_arrows(schema, root)
        assert_named_regions(root, schema)
        if show_references:
            labels = [
                "".join(t.itertext())
                for t in root.iter("{http://www.w3.org/2000/svg}text")
            ]
            assert sum("FK →" in label for label in labels) == 6
        measurements[content] = measure_layout(target, schema, show_types=True)
        native[content] = target.read_bytes()

    monkeypatch.setattr(d2_refinement, "render_d2", spy)
    selected = d2_refinement.render_optimized(schema, source, image, **options)
    winner = source.read_text()
    assert image.read_bytes() == native[winner]
    assert 1 <= len(native) <= 4
    compact = build_d2(schema, **options, layout_strategy="compact")
    previous = (
        compact
        if compact in measurements
        and improves_layout(measurements[compact], measurements[original])
        else original
    )
    if selected.endswith(("-ordered", "-paired")):
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
