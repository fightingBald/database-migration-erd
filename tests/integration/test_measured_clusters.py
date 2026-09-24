"""Measured cluster planning must earn its place through real SVG geometry."""

import pytest

from erd_generator.d2 import build_d2
from erd_generator.d2_geometry import (
    improves_affinity,
    improves_layout,
    improves_packing,
    measure_layout,
)
from erd_generator.d2_refinement import render_optimized
from erd_generator.d2_renderer import render_d2
from tests.support.schemas import uneven_business_schema

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("topology", ["hub", "sparse", "dense", "auto"])
def test_uneven_clusters_select_verified_improvements_or_keep_baseline(
    tmp_path, topology
):
    schema, layout = uneven_business_schema(topology)
    if topology == "auto":
        layout = None
    options = dict(show_types=True, layout_config=layout)
    source = tmp_path / "schema.d2"
    source.write_text(build_d2(schema, **options))
    baseline_image = tmp_path / "before.svg"
    render_d2(source, baseline_image)
    baseline = measure_layout(baseline_image, schema, **options)
    assert len(baseline.group_sizes) == 6
    assert all(w > 0 and h > 0 for _, w, h in baseline.group_sizes)

    image = tmp_path / "after.svg"
    selected = render_optimized(schema, source, image, **options)
    actual = measure_layout(image, schema, **options)
    if topology == "hub":
        assert selected.endswith("-packed")
        assert actual.area <= baseline.area * 0.8
        assert actual.longest < baseline.longest
    if selected == "balanced":
        assert image.read_bytes() == baseline_image.read_bytes()
    else:
        assert (
            improves_packing(actual, baseline)
            or improves_layout(actual, baseline)
            or improves_affinity(actual, baseline)
        )
