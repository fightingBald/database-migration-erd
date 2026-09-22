"""Verify actual ELK geometry, including table sizes and FK row endpoints."""

import re
import xml.etree.ElementTree as ET
from itertools import pairwise
from pathlib import Path

import pytest

from erd_generator.d2 import build_d2
from erd_generator.d2_renderer import render_d2
from erd_generator.schema import Column, ForeignKey, Table
from tests.support.schemas import related_schema, table
from tests.support.svg import (
    NS,
    arrow_routes,
    assert_compact,
    assert_fk_arrows,
    assert_no_overlaps,
    table_boxes,
)

pytestmark = pytest.mark.integration


def render(
    schema, directory: Path, *, direction="right", style="clean", grouping="auto"
):
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "schema.d2"
    source.write_text(
        build_d2(
            schema, show_types=True, direction=direction, style=style, grouping=grouping
        ),
        encoding="utf-8",
    )
    render_d2(source, source.with_suffix(".svg"))
    return ET.parse(source.with_suffix(".svg")).getroot()


@pytest.mark.parametrize("count", [4, 12])
@pytest.mark.parametrize("direction", ["right", "down"])
def test_isolated_tables_use_multiple_rows_and_columns(tmp_path, count, direction):
    schema = {f"app.table_{i:02}": table(f"app.table_{i:02}") for i in range(count)}
    root = render(schema, tmp_path, direction=direction)
    boxes = table_boxes(root)
    assert set(boxes) == set(schema)
    assert_compact(root, boxes)
    assert all(b["header"] == 36 and b["height"] == 144 for b in boxes.values())
    assert not [
        p for p in root.iter(NS + "path") if "connection" in p.get("class", "").split()
    ]


def test_different_table_heights_do_not_stretch_rows(tmp_path):
    schema = {
        f"app.table_{i}": table(f"app.table_{i}", fields)
        for i, fields in enumerate([2, 3, 4, 7, 8, 12, 15, 18])
    }
    root = render(schema, tmp_path)
    boxes = table_boxes(root)
    assert set(boxes) == set(schema)
    assert_compact(root, boxes)
    for name, box in boxes.items():
        assert box["header"] == 36
        assert box["height"] == 36 * (len(schema[name].columns) + 1)


@pytest.mark.parametrize("style", ["clean", "classic"])
@pytest.mark.parametrize("direction", ["right", "down"])
def test_mixed_components_keep_fk_row_endpoints(tmp_path, style, direction):
    schema = {name: table(name, 5) for name in ("parent", "child", "roles", "users")}
    schema["child"].foreign_keys = [
        ForeignKey(("field_1", "field_3"), "parent", ("id", "field_2"), "fk_pair")
    ]
    schema["users"].foreign_keys = [ForeignKey(("field_1",), "roles", ("id",))]
    schema["staff"] = table("staff")
    schema["staff"].foreign_keys = [ForeignKey(("field_1",), "staff", ("id",))]
    schema.update({f"孤立表_{i}": table(f"孤立表_{i}", i + 2) for i in range(3)})
    root = render(schema, tmp_path, style=style, direction=direction)
    boxes = table_boxes(root)
    assert set(boxes) == set(schema)
    assert_compact(root, boxes)
    paths = [
        p for p in root.iter(NS + "path") if "connection" in p.get("class", "").split()
    ]
    assert len(paths) == 4
    endpoints = []
    for path in paths:
        coords = list(map(float, re.findall(r"-?\d+(?:\.\d+)?", path.get("d"))))
        endpoints.append((coords[0], coords[1], coords[-2], coords[-1]))
    for child, column, parent, ref in (
        ("child", "field_1", "parent", "id"),
        ("child", "field_3", "parent", "field_2"),
        ("users", "field_1", "roles", "id"),
    ):
        origin, target = boxes[child], boxes[parent]
        row = [c.name for c in schema[child].columns].index(column)
        ref_row = [c.name for c in schema[parent].columns].index(ref)
        source_y = origin["y"] + origin["header"] * (row + 1.5)
        target_y = target["y"] + target["header"] * (ref_row + 1.5)
        # ELK may choose either side of a field, especially for downward flow.
        # The actual column row must remain exact regardless of that choice.
        assert any(
            min(abs(x1 - origin["x"]), abs(x1 - origin["x"] - origin["width"])) < 3
            and abs(y1 - source_y) < 1
            and min(abs(x2 - target["x"]), abs(x2 - target["x"] - target["width"])) < 5
            and abs(y2 - target_y) < 1
            for x1, y1, x2, y2 in endpoints
        )


def test_packed_names_do_not_collide_with_containers_or_d2_keywords(tmp_path):
    names = (
        "_erd_column_0",
        "_erd_component_0",
        'public.${literal}."quoted"\\路径',
        "shape",
    )
    schema = {name: table(name) for name in names}
    schema["empty"] = Table("empty")
    root = render(schema, tmp_path)
    boxes = table_boxes(root)
    assert set(boxes) == set(schema)
    assert_no_overlaps(boxes)


def test_forty_related_tables_reduce_canvas_and_routes_without_losing_arrows(tmp_path):
    schema = related_schema()
    flat = render(schema, tmp_path / "flat", grouping="none")
    grouped = render(schema, tmp_path / "grouped")
    boxes = table_boxes(grouped)
    assert set(boxes) == set(schema)
    assert_no_overlaps(boxes)
    assert_fk_arrows(schema, grouped)

    def area(root):
        _, _, width, height = map(float, root.get("viewBox").split())
        return width * height

    def lengths(root):
        return [
            sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in pairwise(route))
            for route in arrow_routes(root)
        ]

    assert area(grouped) < 0.85 * area(flat)
    assert sum(lengths(grouped)) < 0.9 * sum(lengths(flat))
    assert max(lengths(grouped)) < max(lengths(flat))
    # Each inferred domain occupies its own spatial region, despite interleaved names.
    domains = {}
    for group in range(4):
        members = [boxes[f"app.table_{i * 4 + group:02}"] for i in range(10)]
        x, y = min(b["x"] for b in members), min(b["y"] for b in members)
        domains[group] = {
            "x": x,
            "y": y,
            "width": max(b["x"] + b["width"] for b in members) - x,
            "height": max(b["y"] + b["height"] for b in members) - y,
        }
    assert_no_overlaps(domains)


@pytest.mark.parametrize("direction", ["right", "down", "left", "up"])
@pytest.mark.parametrize("style", ["clean", "classic"])
def test_grouped_composite_cycles_and_special_names_keep_field_arrows(
    tmp_path, direction, style
):
    names = ["_erd_group_0", 'public.${literal}."quoted"\\路径', "shape"]
    names.extend(f"table_{i}" for i in range(3, 14))
    schema = {name: table(name, 5) for name in names}
    for start in (0, 7):
        for i in range(start + 1, start + 7):
            schema[names[i]].foreign_keys.append(
                ForeignKey(
                    ("field_1", "field_3"), names[start], ("id", "field_2"), "fk_pair"
                )
            )
            if i > start + 1:
                schema[names[i]].foreign_keys.append(
                    ForeignKey(("field_4",), names[i - 1], ("id",))
                )
    schema[names[0]].foreign_keys = [
        ForeignKey(("field_4",), names[1], ("id",)),
        ForeignKey(("field_1",), names[0], ("id",)),
    ]
    schema[names[7]].foreign_keys = [
        ForeignKey(
            ("field_1", "field_3"), names[0], ("id", "field_2"), "fk_cross_group"
        )
    ]
    schema.update({f"isolated_{i}": table(f"isolated_{i}") for i in range(3)})
    root = render(schema, tmp_path, direction=direction, style=style)
    assert "_erd_group_" in (tmp_path / "schema.d2").read_text()
    boxes = table_boxes(root)
    assert set(boxes) == set(schema)
    assert_no_overlaps(boxes)
    assert_fk_arrows(schema, root)


def test_grouped_shared_identity_table_retains_every_incoming_relationship(tmp_path):
    schema = related_schema()
    for value in schema.values():
        value.columns.append(Column("identity_id", "INT"))
        value.foreign_keys.append(ForeignKey(("identity_id",), "identity", ("id",)))
    schema["identity"] = table("identity")
    root = render(schema, tmp_path)
    boxes = table_boxes(root)
    assert set(boxes) == set(schema)
    assert_no_overlaps(boxes)
    assert_fk_arrows(schema, root)
