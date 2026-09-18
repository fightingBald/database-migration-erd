"""Keep the same 30-table input readable without losing business or FK details."""

from pathlib import Path

import pytest

from erd_generator.d2 import build_d2
from erd_generator.sql_parser import parse_schema_from_sql
from erd_generator.validation import validate_schema
from tests.integration.test_business_layout import (
    assert_named_regions,
    region_boxes,
    render,
)
from tests.integration.test_compact_layout import NS, arrow_routes

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("direction", ["right", "left", "up", "down"])
@pytest.mark.parametrize("style", ["clean", "classic"])
def test_thirty_tables_keep_four_regions_all_fields_and_shorter_routes(
    tmp_path, direction, style
):
    schema = {}
    fixture = Path(__file__).resolve().parents[1] / "fixtures/library_30_tables.sql"
    parse_schema_from_sql(fixture.read_text(), schema)
    assert len(schema) == 30
    assert sum(len(t.columns) for t in schema.values()) == 123
    assert len(validate_schema(schema).relationships) == 34
    root = render(schema, tmp_path, direction=direction, style=style)
    assert_named_regions(root, schema)
    assert len(region_boxes(root)) == 4
    for group in root.iter(NS + "g"):
        if not any(
            "class_header" in r.get("class", "") for r in group.findall(NS + "rect")
        ):
            continue
        labels = ["".join(t.itertext()) for t in group.findall(NS + "text")]
        assert labels[1::3] == [c.name for c in schema[labels[0]].columns]
    assert (tmp_path / "schema.d2").read_text() == build_d2(
        dict(reversed(list(schema.items()))),
        show_types=True,
        direction=direction,
        style=style,
    )

    if direction == "right" and style == "clean":
        # Previous automatic layout: 12,458,310 area, 26,361 total route length,
        # 4,134 longest route. Leave tolerance rather than freezing coordinates.
        _, _, width, height = map(float, root.get("viewBox").split())
        lengths = [
            sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(route, route[1:]))
            for route in arrow_routes(root)
        ]
        assert width * height < 10_000_000
        assert sum(lengths) < 23_000
        assert max(lengths) < 2_800
