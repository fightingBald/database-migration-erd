"""True two-pass placement must repair the external-leaf strip regression."""

from copy import deepcopy

import pytest

from erd_generator.d2 import build_d2, build_partitioned_d2
from erd_generator.d2_geometry import measure_svg
from erd_generator.d2_refinement import render_optimized
from erd_generator.d2_renderer import render_source
from erd_generator.schema import Index
from erd_generator.svg_partitions import compose_partitions
from tests.support.schemas import business_schema, externally_linked_schema

pytestmark = pytest.mark.integration


def test_sixty_four_tables_with_external_leaves_are_compact_and_fully_connected(
    tmp_path,
):
    schema = externally_linked_schema()
    original = build_d2(schema, show_types=True)
    baseline = measure_svg(render_source(original), schema, show_types=True)
    output = tmp_path / "schema.svg"
    assert render_optimized(schema, original, output, show_types=True) == "partitioned"
    assert set(tmp_path.iterdir()) == {output}
    image = output.read_text()
    actual = measure_svg(image, schema, show_types=True)
    assert actual.area < baseline.area * 0.65
    assert max(actual.width, actual.height) < max(baseline.width, baseline.height) * 0.7
    assert actual.longest < baseline.longest
    assert actual.aspect < 2


@pytest.mark.parametrize(
    "direction,style,details",
    [
        ("right", "clean", True),
        ("down", "clean", False),
        ("left", "classic", True),
        ("up", "classic", False),
    ],
)
def test_partition_composition_keeps_indexes_composite_ports_and_self_references(
    direction, style, details
):
    schema = business_schema()
    name = sorted(schema)[0]
    schema[name].indexes.append(
        Index("ix_dummy", ("field_1",), column_names=("field_1",))
    )
    original = deepcopy(schema)
    options = dict(
        show_types=details,
        show_indexes=details,
        direction=direction,
        style=style,
        show_references=True,
    )
    local = render_source(build_partitioned_d2(schema, **options))
    image = compose_partitions(local, schema, style=style)
    metrics = measure_svg(image, schema, show_types=details, show_indexes=details)
    assert len(metrics.group_sizes) == 3
    assert metrics.total_length > 0
    assert schema == original
