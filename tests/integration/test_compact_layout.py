"""Verify actual ELK geometry, including table sizes and FK row endpoints."""

from itertools import combinations
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import pytest

from erd_generator.d2 import build_d2
from erd_generator.d2_renderer import render_d2
from erd_generator.schema import Column, ForeignKey, Table

pytestmark = pytest.mark.integration
NS = "{http://www.w3.org/2000/svg}"


def table(name, fields=3):
    return Table(
        name,
        columns=[Column("id", "INT", is_primary_key=True)]
        + [Column(f"field_{i}", "TEXT") for i in range(1, fields)],
    )


def render(schema, directory: Path, *, direction="right", style="clean"):
    source = directory / "schema.d2"
    source.write_text(
        build_d2(schema, show_types=True, direction=direction, style=style),
        encoding="utf-8",
    )
    render_d2(source, source.with_suffix(".svg"))
    return ET.parse(source.with_suffix(".svg")).getroot()


def table_boxes(root):
    boxes = {}
    for group in root.iter(NS + "g"):
        rects = group.findall(NS + "rect")
        headers = [r for r in rects if "class_header" in r.get("class", "")]
        if not headers:
            continue
        label = group.find(NS + "text")
        name = "".join(label.itertext())
        assert name not in boxes
        body = next(r for r in rects if "shape" in r.get("class", "").split())
        boxes[name] = {
            key: float(body.get(key)) for key in ("x", "y", "width", "height")
        }
        boxes[name]["header"] = float(headers[0].get("height"))
    return boxes


def assert_no_overlaps(boxes):
    for a, b in combinations(boxes.values(), 2):
        assert (
            a["x"] + a["width"] <= b["x"]
            or b["x"] + b["width"] <= a["x"]
            or a["y"] + a["height"] <= b["y"]
            or b["y"] + b["height"] <= a["y"]
        )


def assert_compact(root, boxes):
    _, _, width, height = map(float, root.get("viewBox").split())
    assert max(width / height, height / width) < 2.1
    assert len({b["x"] for b in boxes.values()}) > 1
    assert len({b["y"] for b in boxes.values()}) > 1
    assert_no_overlaps(boxes)


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
