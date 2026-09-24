"""Shared assertions for native SVG tables, regions and FK field endpoints."""

import re
from itertools import combinations

from erd_generator.d2_business import plan_groups
from erd_generator.validation import validate_schema

NS = "{http://www.w3.org/2000/svg}"


def offsets(root):
    result = {}

    def visit(element, x, y):
        if element.get("data-erd-partition") is not None:
            transform = element.get("transform")
            assert transform.startswith("translate(") and transform.endswith(")")
            dx, dy = map(float, transform[10:-1].split())
            x, y = x + dx, y + dy
        result[element] = (x, y)
        for child in element:
            visit(child, x, y)

    visit(root, 0, 0)
    return result


def table_boxes(root):
    boxes = {}
    shifts = offsets(root)
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
        boxes[name]["x"] += shifts[group][0]
        boxes[name]["y"] += shifts[group][1]
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


def arrow_routes(root):
    routes = []
    shifts = offsets(root)
    for path in root.iter(NS + "path"):
        if "connection" not in path.get("class", "").split():
            continue
        coords = list(map(float, re.findall(r"-?\d+(?:\.\d+)?", path.get("d"))))
        points = list(zip(coords[::2], coords[1::2], strict=True))
        dx, dy = shifts[path]
        points = [(x + dx, y + dy) for x, y in points]
        # Normalize to FK source -> referenced field using the actual arrowhead.
        assert bool(path.get("marker-start")) != bool(path.get("marker-end"))
        if path.get("marker-start"):
            points.reverse()
        routes.append(points)
    return routes


def assert_fk_arrows(schema, root):
    boxes = table_boxes(root)
    routes = arrow_routes(root)
    relationships = validate_schema(schema).relationships
    assert len(routes) == sum(len(fk.columns) for fk in relationships)

    def at_field(point, name, column):
        box = boxes[name]
        row = [c.name for c in schema[name].columns].index(column)
        top = box["y"] + box["header"] * (row + 1)
        # ELK can align horizontal segments away from the row's center. The
        # endpoint must still lie strictly inside the correct SQL field row.
        # Classic arrowheads can end exactly five units outside the table edge.
        return (
            min(abs(point[0] - box["x"]), abs(point[0] - box["x"] - box["width"])) <= 5
            and top + 1 < point[1] < top + box["header"] - 1
        )

    for fk in relationships:
        if fk.table == fk.ref_table:
            continue  # ELK's existing self-loop limitation uses table boundaries.
        for source, target in zip(fk.columns, fk.ref_columns, strict=True):
            assert any(
                at_field(route[0], fk.table, source)
                and at_field(route[-1], fk.ref_table, target)
                for route in routes
            ), (fk.table, source, fk.ref_table, target)


def region_boxes(root):
    result = {}
    shifts = offsets(root)
    for group in root.iter(NS + "g"):
        label = group.find(NS + "text")
        if label is None:
            continue
        text = "".join(label.itertext())
        if not text:
            continue
        shape = group.find(f"{NS}g[@class='shape']/{NS}rect")
        if shape is not None:
            result[text] = {
                key: float(shape.get(key)) for key in ("x", "y", "width", "height")
            }
            result[text]["x"] += shifts[group][0]
            result[text]["y"] += shifts[group][1]
    return result


def assert_named_regions(root, schema, config=None):
    boxes, regions = table_boxes(root), region_boxes(root)
    expected = [
        g
        for g in plan_groups(
            schema, validate_schema(schema).relationships, config=config
        )
        if g.label
    ]
    assert len(regions) == len(expected)
    assert_no_overlaps(regions)
    for group in expected:
        region = regions[group.label]
        for name in group.tables:
            box = boxes[name]
            assert region["x"] <= box["x"] and region["y"] + 24 <= box["y"]
            assert box["x"] + box["width"] <= region["x"] + region["width"] + 1
            assert box["y"] + box["height"] <= region["y"] + region["height"] + 1
