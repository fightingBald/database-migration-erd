"""Compose native cluster drawings at fixed positions and route boundary FKs."""

import base64
import math
import re
import xml.etree.ElementTree as ET
from itertools import pairwise, product

from .d2_affinity import group_weights
from .d2_business import plan_groups
from .d2_geometry import svg_routes
from .diagram_packing import CANVAS_PAD, pack_rectangles
from .diagram_routing import (
    Rect,
    crossing_cost,
    path_length,
    route,
    segment_clear,
    simplify,
)
from .layout_config import LayoutConfig
from .schema import Schema
from .validation import validate_schema

NS = "{http://www.w3.org/2000/svg}"
HTML_NS = "{http://www.w3.org/1999/xhtml}"
PARTITION = re.compile(r"^_erd_partition_(\d+)(?:\.|$)")


def _rect(element):
    if element is None:
        raise ValueError("missing native rectangle")
    values = tuple(float(element.get(k, "nan")) for k in ("x", "y", "width", "height"))
    if not all(map(math.isfinite, values)) or min(values[2:]) <= 0:
        raise ValueError("invalid native rectangle")
    return Rect(*values)


def _shift(box, dx, dy):
    return Rect(box.x + dx, box.y + dy, box.width, box.height)


def _table_boxes(root):
    boxes, headers, footprints = {}, {}, {}
    for group in root.iter(NS + "g"):
        header = next(
            (
                r
                for r in group.findall(NS + "rect")
                if "class_header" in r.get("class", "")
            ),
            None,
        )
        if header is not None:
            label = group.find(NS + "text")
            if label is None:
                raise ValueError("missing native table label")
            name = "".join(label.itertext())
            boxes[name] = _rect(
                next(
                    (
                        r
                        for r in group.findall(NS + "rect")
                        if "shape" in r.get("class", "").split()
                    ),
                    None,
                )
            )
            headers[name] = _rect(header).height
        footer = group.find(
            f"{NS}g/{NS}foreignObject/.//{HTML_NS}div[@data-erd-index-table]"
        )
        if footer is not None:
            footprints[footer.get("data-erd-index-table")] = _rect(
                group.find(f"{NS}g[@class='shape']/{NS}rect")
            )
    return (
        boxes,
        headers,
        {name: footprints.get(name, box) for name, box in boxes.items()},
    )


def _boundary_route(a, b, ay, by, af, bf, obstacles, occupied):
    # Ports remain on the exact SQL rows. Lead segments clear the table's full
    # footprint (including index-caption padding) before turning.
    starts = [((a.x, ay), (af.x - 10, ay)), ((a.right, ay), (af.right + 10, ay))]
    ends = [((b.x, by), (bf.x - 10, by)), ((b.right, by), (bf.right + 10, by))]
    choices = []
    for (start, leave), (end, enter) in product(starts, ends):
        try:
            middle = route(leave, enter, obstacles)
        except ValueError:
            continue
        points = simplify([start, *middle, end])
        choices.append((path_length(points), start, leave, end, enter, points))
    if not choices:
        raise ValueError("no boundary route")
    # Avoid trading a long winding route for fewer crossings. Each field arrow
    # may detour only modestly from its shortest obstacle-free route.
    limit = min(c[0] for c in choices) * 1.15 + 48
    best, best_score = None, float("inf")
    for length, start, leave, end, enter, shortest in choices:
        if length > limit:
            continue
        leads = abs(start[0] - leave[0]) + abs(end[0] - enter[0])
        for points in (
            shortest,
            simplify(
                [
                    start,
                    *route(
                        leave,
                        enter,
                        obstacles,
                        occupied=occupied,
                        max_length=limit - leads,
                    ),
                    end,
                ]
            ),
        ):
            length = path_length(points)
            score = length + sum(
                crossing_cost(p, q, occupied) for p, q in pairwise(points)
            )
            if length <= limit and score < best_score:
                best, best_score = points, score
    return best


def compose_partitions(
    svg: str,
    schema: Schema,
    *,
    layout_config: LayoutConfig | None = None,
    style: str = "clean",
) -> str:
    """Move native groups without touching their shapes or internal routes.

    A single rendered document supplies shared fonts, styles, masks and IDs.
    Only explicit translation wrappers and new boundary arrows are added.
    The caller must validate the completed drawing before publication.
    """
    root = ET.fromstring(svg)
    drawing = root.find(NS + "svg")
    if drawing is None:
        raise ValueError("missing native drawing")
    validation = validate_schema(schema)
    if validation.errors:
        raise ValueError("invalid schema")
    groups = plan_groups(schema, validation.relationships, config=layout_config)
    owners = {n: g.key for g in groups for n in g.tables}
    bounds, elements = {}, {g.key: [] for g in groups}
    icons = []
    for element in drawing.findall(NS + "g"):
        if element.get("class") == "appendix-icon":
            icons.append(element)
            continue
        try:
            name = base64.b64decode(element.get("class", ""), validate=True).decode()
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("unknown native group") from exc
        match = PARTITION.match(name)
        if match is None or int(match[1]) >= len(groups):
            raise ValueError("unknown native partition")
        key = groups[int(match[1])].key
        elements[key].append(element)
        if name == f"_erd_partition_{match[1]}":
            bounds[key] = _rect(element.find(f"{NS}g[@class='shape']/{NS}rect"))
    if set(bounds) != set(elements):
        raise ValueError("incomplete native partitions")
    for icon in icons:
        match = re.fullmatch(
            r"translate\(([-+\d.eE]+) ([-+\d.eE]+)\)", icon.get("transform", "")
        )
        if match is None:
            raise ValueError("unknown native icon")
        x, y = map(float, match.groups())
        owners_at_icon = [
            key for key, box in bounds.items() if box.inside((x + 16, y + 16))
        ]
        if len(owners_at_icon) != 1:
            raise ValueError("ambiguous native icon")
        elements[owners_at_icon[0]].append(icon)
    boxes, headers, footprints = _table_boxes(root)
    if set(boxes) != set(schema):
        raise ValueError("incomplete native tables")
    positions = pack_rectangles(
        {key: (box.width, box.height) for key, box in bounds.items()},
        group_weights(owners, validation.relationships),
    )
    for key, box in positions.items():
        dx, dy = box.x - bounds[key].x, box.y - bounds[key].y
        wrapper = ET.SubElement(
            drawing,
            NS + "g",
            {
                "data-erd-partition": key,
                "transform": f"translate({dx:g} {dy:g})",
            },
        )
        for element in elements[key]:
            drawing.remove(element)
            wrapper.append(element)
        for name in boxes:
            if owners[name] == key:
                boxes[name] = _shift(boxes[name], dx, dy)
                footprints[name] = _shift(footprints[name], dx, dy)
    width = max(r.right for r in positions.values()) + CANVAS_PAD
    height = max(r.bottom for r in positions.values()) + CANVAS_PAD
    root.set("viewBox", f"0 0 {width:g} {height:g}")
    root.set("data-erd-layout", "partitioned")
    drawing.set("viewBox", root.get("viewBox"))
    drawing.set("width", f"{width:g}")
    drawing.set("height", f"{height:g}")
    background = drawing.find(NS + "rect")
    if background is None:
        raise ValueError("missing native background")
    for key, value in {
        "x": "0",
        "y": "0",
        "width": f"{width:g}",
        "height": f"{height:g}",
    }.items():
        background.set(key, value)

    color = "#64748B" if style == "clean" else "#000000"
    marker = ET.SubElement(
        drawing,
        NS + "marker",
        {
            "id": "erd-boundary-arrow",
            "viewBox": "0 0 10 10",
            "refX": "10",
            "refY": "5",
            "markerWidth": "10",
            "markerHeight": "10",
            "orient": "auto",
            "markerUnits": "userSpaceOnUse",
        },
    )
    ET.SubElement(marker, NS + "path", {"d": "M 0 0 L 10 5 L 0 10 Z", "fill": color})
    occupied = svg_routes(root)
    for fk in validation.relationships:
        source, target = owners[fk.table], owners[fk.ref_table]
        if source == target:
            continue
        local = {source, target}
        obstacles = [r.padded(10) for k, r in footprints.items() if owners[k] in local]
        obstacles.extend(r.padded(10) for k, r in positions.items() if k not in local)
        obstacles.extend(
            Rect(positions[g.key].x, positions[g.key].y, positions[g.key].width, 48)
            for g in groups
            if g.key in local and g.label
        )
        a, b = boxes[fk.table], boxes[fk.ref_table]
        other_tables = [
            r for n, r in footprints.items() if n not in {fk.table, fk.ref_table}
        ]
        for column, remote in zip(fk.columns, fk.ref_columns, strict=True):
            row_a = next(
                i for i, c in enumerate(schema[fk.table].columns) if c.name == column
            )
            row_b = next(
                i
                for i, c in enumerate(schema[fk.ref_table].columns)
                if c.name == remote
            )
            points = _boundary_route(
                a,
                b,
                a.y + headers[fk.table] * (row_a + 1.5),
                b.y + headers[fk.ref_table] * (row_b + 1.5),
                footprints[fk.table],
                footprints[fk.ref_table],
                obstacles,
                occupied,
            )
            # Independently verify every segment against other table footprints.
            if not all(segment_clear(p, q, other_tables) for p, q in pairwise(points)):
                raise ValueError("boundary route intersects a table")
            occupied.append(points)
            path = ET.SubElement(
                drawing,
                NS + "path",
                {
                    "d": "M " + " L ".join(f"{x:g} {y:g}" for x, y in points),
                    "class": "connection",
                    "data-erd-boundary": "true",
                    "fill": "none",
                    "stroke": color,
                    "stroke-width": "2",
                    "stroke-linejoin": "round",
                    "marker-end": "url(#erd-boundary-arrow)",
                },
            )
            ET.SubElement(
                path, NS + "title"
            ).text = f"{fk.name + ': ' if fk.name else ''}{fk.table}.{column} → {fk.ref_table}.{remote}"
    return ET.tostring(root, encoding="unicode")
