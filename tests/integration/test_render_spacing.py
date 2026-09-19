"""Compare compact routing with the previous ELK spacing across graph shapes."""

import os
import subprocess
import xml.etree.ElementTree as ET

import pytest

from erd_generator.d2 import build_d2
from erd_generator.d2_renderer import render_d2
from erd_generator.schema import ForeignKey
from tests.integration.test_business_layout import business_schema
from tests.integration.test_compact_layout import (
    arrow_routes,
    assert_fk_arrows,
    assert_no_overlaps,
    related_schema,
    table,
    table_boxes,
)

pytestmark = pytest.mark.integration


def scenario(shape):
    if shape == "communities":
        return related_schema()
    if shape == "composite_cycles":
        return business_schema()
    names = tuple(f"demo_library.t{i:02}" for i in range(18))
    schema = {n: table(n, 3 + i % 7) for i, n in enumerate(names)}
    if shape != "isolated":
        for i, name in enumerate(names[1:], 1):
            target = names[0] if shape == "star" else names[i - 1]
            schema[name].foreign_keys = [ForeignKey(("field_1",), target, ("id",))]
    return schema


@pytest.mark.parametrize(
    "shape", ["isolated", "chain", "star", "communities", "composite_cycles"]
)
@pytest.mark.parametrize("direction", ["right", "down"])
def test_spacing_reduces_routes_without_losing_fields(tmp_path, shape, direction):
    schema = scenario(shape)
    source = tmp_path / "schema.d2"
    source.write_text(build_d2(schema, show_types=True, direction=direction))
    current = tmp_path / "current.svg"
    render_d2(source, current)
    baseline = tmp_path / "baseline.svg"
    subprocess.run(
        [
            "d2",
            "--layout=elk",
            "--elk-nodeSelfLoop=100",
            "--elk-padding=[top=16,left=16,bottom=16,right=16]",
            "--elk-nodeNodeBetweenLayers=70",
            "--elk-edgeNodeBetweenLayers=40",
            "--theme=0",
            "--dark-theme=-1",
            "--sketch=false",
            "--scale=-1",
            "--pad=100",
            "--watch=false",
            str(source),
            str(baseline),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
        env={k: v for k, v in os.environ.items() if not k.startswith(("D2_", "ELK_"))},
    )
    measurements = []
    for path in (baseline, current):
        root = ET.parse(path).getroot()
        boxes = table_boxes(root)
        assert set(boxes) == set(schema)
        assert_no_overlaps(boxes)
        assert_fk_arrows(schema, root)
        _, _, width, height = map(float, root.get("viewBox").split())
        lengths = [
            sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(route, route[1:]))
            for route in arrow_routes(root)
        ]
        measurements.append((width * height, sum(lengths), max(lengths, default=0)))
    old, new = measurements
    if shape == "isolated":
        assert new == old
    else:
        assert new[0] < old[0]
        assert new[1] < old[1]
        assert new[2] <= old[2]
