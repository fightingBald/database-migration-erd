"""Verify native and composed SVG geometry without changing diagram content."""

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from itertools import combinations, pairwise
from pathlib import Path

from .d2_affinity import group_weights, weighted_distance
from .d2_business import plan_groups
from .d2_indexes import FOOTER_STYLE, index_footer
from .d2_renderer import D2RenderError
from .diagram_routing import Rect, path_length, segment_clear
from .layout_config import LayoutConfig
from .schema import Schema
from .validation import validate_schema

NS = "{http://www.w3.org/2000/svg}"
HTML_NS = "{http://www.w3.org/1999/xhtml}"
NUMBER = re.compile(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?")


@dataclass(frozen=True)
class LayoutMetrics:
    width: float
    height: float
    table_area: float
    total_length: float
    longest: float
    crossings: int
    affinity_distance: float = 0
    group_sizes: tuple[tuple[str, float, float], ...] = ()
    crossing_points: int = 0

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def aspect(self) -> float:
        return max(self.width, self.height) / min(self.width, self.height)


def _preserves_geometry(candidate: LayoutMetrics, baseline: LayoutMetrics) -> bool:
    """Bound native layout shape, longest route and approximate crossings."""
    return (
        max(candidate.width, candidate.height) <= max(baseline.width, baseline.height)
        and candidate.aspect <= max(2.0, baseline.aspect)
        and candidate.longest <= baseline.longest
        and candidate.crossings
        <= baseline.crossings + max(2, int(baseline.crossings * 0.05))
    )


def improves_layout(candidate: LayoutMetrics, baseline: LayoutMetrics) -> bool:
    """Require 5% less area without longer routes or a longer strip."""
    return (
        candidate.area <= baseline.area * 0.95
        and candidate.total_length <= baseline.total_length
        and _preserves_geometry(candidate, baseline)
    )


def improves_affinity(candidate: LayoutMetrics, baseline: LayoutMetrics) -> bool:
    """Require 5% closer related clusters without degrading the old winner."""
    return (
        baseline.affinity_distance > 0
        and candidate.affinity_distance <= baseline.affinity_distance * 0.95
        and candidate.area <= baseline.area
        and candidate.total_length <= baseline.total_length
        and _preserves_geometry(candidate, baseline)
    )


def improves_packing(candidate: LayoutMetrics, baseline: LayoutMetrics) -> bool:
    """Trade at most 3% total route length for at least 10% canvas reduction.

    The longest route, cluster distance and longest canvas side may not grow.
    Compare against the existing winner, never accumulate candidate tolerances.
    """
    return (
        candidate.area <= baseline.area * 0.9
        and candidate.total_length <= baseline.total_length * 1.03
        and candidate.affinity_distance <= baseline.affinity_distance
        and _preserves_geometry(candidate, baseline)
    )


def improves_partitioned(
    candidate: LayoutMetrics, baseline: LayoutMetrics, arrows: int
) -> bool:
    """A major compaction may trade bounded extra crossings for readability.

    Unlike ordering hints, independent placement changes the route topology.
    Require 25% less area, 10% shorter longest side, no longer longest route,
    and bounded extra intersections. Shared trunks can put many arrow pairs
    through one physical crossing, so check both counts rather than conflating
    them: at most one extra crossing location per four field arrows, with at
    most two extra intersecting pairs per field arrow.
    """
    return (
        candidate.area <= baseline.area * 0.75
        and max(candidate.width, candidate.height)
        <= max(baseline.width, baseline.height) * 0.9
        and candidate.aspect <= 2
        and candidate.longest <= baseline.longest
        and candidate.total_length <= baseline.total_length * 1.1
        and candidate.crossings <= baseline.crossings + max(4, 2 * arrows)
        and candidate.crossing_points <= baseline.crossing_points + max(4, arrows // 4)
        and candidate.affinity_distance <= baseline.affinity_distance * 1.1
    )


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @classmethod
    def read(cls, element: ET.Element, offset=(0.0, 0.0)) -> "Box":
        values = tuple(
            float(element.get(k, "nan")) for k in ("x", "y", "width", "height")
        )
        if not all(map(math.isfinite, values)) or min(values[2:]) <= 0:
            raise ValueError("shape dimensions")
        return cls(values[0] + offset[0], values[1] + offset[1], *values[2:])

    def contains(self, other: "Box", *, heading: float = 0) -> bool:
        return (
            self.x <= other.x
            and self.y + heading <= other.y
            and other.x + other.width <= self.x + self.width + 1
            and other.y + other.height <= self.y + self.height + 1
        )

    def at_border(self, point: tuple[float, float]) -> bool:
        x, y = point
        return (
            self.x - 5 <= x <= self.x + self.width + 5
            and self.y - 5 <= y <= self.y + self.height + 5
            and min(
                abs(x - self.x),
                abs(x - self.x - self.width),
                abs(y - self.y),
                abs(y - self.y - self.height),
            )
            <= 5
        )


def _no_overlaps(boxes: list[Box]) -> None:
    for a, b in combinations(boxes, 2):
        if not (
            a.x + a.width <= b.x
            or b.x + b.width <= a.x
            or a.y + a.height <= b.y
            or b.y + b.height <= a.y
        ):
            raise ValueError("overlapping shapes")


def _offsets(root: ET.Element) -> dict[ET.Element, tuple[float, float]]:
    """Only composition wrappers translate native diagram coordinates."""
    result = {}

    def visit(element, offset):
        if element.get("data-erd-partition") is not None:
            match = re.fullmatch(
                r"translate\(([-+\d.eE]+) ([-+\d.eE]+)\)", element.get("transform", "")
            )
            if match is None or not all(map(math.isfinite, map(float, match.groups()))):
                raise ValueError("partition translation")
            dx, dy = map(float, match.groups())
            offset = (offset[0] + dx, offset[1] + dy)
        result[element] = offset
        for child in element:
            visit(child, offset)

    visit(root, (0.0, 0.0))
    return result


def svg_routes(root: ET.Element) -> list[list[tuple[float, float]]]:
    routes = []
    offsets = _offsets(root)
    for path in root.iter(NS + "path"):
        if "connection" not in path.get("class", "").split():
            continue
        data = path.get("d", "")
        numbers = list(map(float, NUMBER.findall(data)))
        # The pinned renderer emits absolute move/line/Bezier coordinate pairs.
        if (
            len(numbers) < 4
            or len(numbers) % 2
            or not all(map(math.isfinite, numbers))
            or re.search(r"[^MLCQSTZ\s,]", NUMBER.sub("", data))
        ):
            raise ValueError("unsupported route geometry")
        if bool(path.get("marker-start")) == bool(path.get("marker-end")):
            raise ValueError("arrow direction")
        dx, dy = offsets[path]
        points = [
            (x + dx, y + dy) for x, y in zip(numbers[::2], numbers[1::2], strict=True)
        ]
        routes.append(points[::-1] if path.get("marker-start") else points)
    return routes


def _crossing_counts(routes: list[list[tuple[float, float]]]) -> tuple[int, int]:
    horizontal, vertical = [], []
    for i, route in enumerate(routes):
        for a, b in pairwise(route):
            if abs(a[1] - b[1]) < 1e-4 and abs(a[0] - b[0]) > 1:
                horizontal.append((i, min(a[0], b[0]), max(a[0], b[0]), a[1]))
            elif abs(a[0] - b[0]) < 1e-4 and abs(a[1] - b[1]) > 1:
                vertical.append((i, min(a[1], b[1]), max(a[1], b[1]), a[0]))
    intersections = {
        (min(i, j), max(i, j), round(x, 2), round(y, 2))
        for i, left, right, y in horizontal
        for j, top, bottom, x in vertical
        if i != j and left + 0.1 < x < right - 0.1 and top + 0.1 < y < bottom - 0.1
    }
    return len(intersections), len({(x, y) for _, _, x, y in intersections})


def measure_layout(path: Path, schema: Schema, **options) -> LayoutMetrics:
    """File adapter for explicitly saved SVG artifacts."""
    return measure_svg(path.read_text(encoding="utf-8"), schema, **options)


def measure_svg(
    svg: str,
    schema: Schema,
    *,
    show_types: bool = False,
    grouping: str = "auto",
    layout_config: LayoutConfig | None = None,
    show_indexes: bool = True,
) -> LayoutMetrics:
    try:
        return _measure(
            ET.fromstring(svg),
            schema,
            show_types,
            grouping,
            layout_config,
            show_indexes,
        )
    except (ET.ParseError, ValueError, KeyError, TypeError, StopIteration) as exc:
        # Never expose XML/SQL payloads through an optimization diagnostic.
        raise D2RenderError(
            "D2 layout verification failed: "
            + (
                str(exc)
                if type(exc) is ValueError
                and str(exc)
                in {
                    "canvas dimensions",
                    "shape dimensions",
                    "table contents",
                    "table membership",
                    "overlapping shapes",
                    "unsupported route geometry",
                    "arrow direction",
                    "connection count",
                    "field endpoints",
                    "business regions",
                    "clipped geometry",
                    "index footer",
                    "route intersects a table",
                }
                else "unexpected SVG structure"
            )
        ) from exc


def _measure(root, schema, show_types, grouping, config, show_indexes):
    offsets = _offsets(root)

    def read_box(element):
        return Box.read(element, offsets[element])

    canvas = tuple(map(float, root.get("viewBox", "").split()))
    if len(canvas) != 4 or not all(map(math.isfinite, canvas)) or min(canvas[2:]) <= 0:
        raise ValueError("canvas dimensions")
    drawing = root.find(NS + "svg")
    viewport = canvas
    if drawing is not None:
        viewport = tuple(map(float, drawing.get("viewBox", "").split()))
        if (
            len(viewport) != 4
            or not all(map(math.isfinite, viewport))
            or min(viewport[2:]) <= 0
            or float(drawing.get("width", "nan")) != canvas[2]
            or float(drawing.get("height", "nan")) != canvas[3]
        ):
            raise ValueError("canvas dimensions")
    bounds = Box(*viewport)
    boxes, headers, regions = {}, {}, []
    for group in root.iter(NS + "g"):
        texts = ["".join(t.itertext()) for t in group.findall(NS + "text")]
        rects = group.findall(NS + "rect")
        header = next((r for r in rects if "class_header" in r.get("class", "")), None)
        if header is not None:
            name = texts[0] if texts else ""
            if name not in schema or name in boxes:
                raise ValueError("table membership")
            box = next(r for r in rects if "shape" in r.get("class", "").split())
            boxes[name], headers[name] = read_box(box), read_box(header).height
            if texts[1::3] != [c.name for c in schema[name].columns] or texts[2::3] != [
                c.data_type if show_types else "" for c in schema[name].columns
            ]:
                raise ValueError("table contents")
        else:
            rectangle = group.find(f"{NS}g[@class='shape']/{NS}rect")
            if rectangle is not None:
                label = group.find(f"{NS}g/{NS}foreignObject")
                if label is not None:
                    spans = label.findall(
                        f".//{HTML_NS}span[@data-erd-index-line='true']"
                    )
                    if spans:
                        regions.append(
                            (
                                "".join("".join(s.itertext()) for s in spans),
                                read_box(rectangle),
                                label,
                            )
                        )
                elif texts and texts[0]:
                    regions.append(
                        (texts[0], read_box(rectangle), group.find(NS + "text"))
                    )
    if set(boxes) != set(schema):
        raise ValueError("table membership")
    footprints = dict(boxes)
    for name, table in schema.items():
        if not show_indexes or not table.indexes:
            continue
        expected_text = "".join(index_footer(table, show_types).splitlines())
        matches = [
            (box.width * box.height, i)
            for i, (label, box, _) in enumerate(regions)
            if label == expected_text and box.contains(boxes[name])
        ]
        if not matches:
            raise ValueError("index footer")
        # A business title could equal a footer; the closest enclosing box is
        # the table's own native container, not an ancestor region.
        _, i = min(matches)
        _, footprint, label = regions.pop(i)
        content = label.find(f".//{HTML_NS}div[@data-erd-index-footer='true']")
        label_box = read_box(label)
        if (
            content is None
            or content.get("style") != FOOTER_STYLE
            or content.get("data-erd-index-table") != name
            or not (
                label_box.y >= boxes[name].y + boxes[name].height
                and abs(label_box.x - boxes[name].x) <= 0.01
                and label_box.width <= boxes[name].width + 1
                and footprint.contains(label_box)
            )
        ):
            raise ValueError("index footer")
        footprints[name] = footprint
    _no_overlaps(list(footprints.values()))
    if not all(bounds.contains(box) for box in footprints.values()):
        raise ValueError("clipped geometry")
    validation = validate_schema(schema)
    groups = plan_groups(
        schema,
        validation.relationships,
        automatic=grouping == "auto",
        config=config,
    )
    centres = {}
    group_sizes = []
    _no_overlaps([box for _, box, _ in regions])
    if not all(bounds.contains(box) for _, box, _ in regions):
        raise ValueError("clipped geometry")
    for group in groups:
        if not group.label:
            members = [footprints[n] for n in group.tables]
            left, top = min(b.x for b in members), min(b.y for b in members)
            right = max(b.x + b.width for b in members)
            bottom = max(b.y + b.height for b in members)
            centres[group.key] = ((left + right) / 2, (top + bottom) / 2)
            group_sizes.append((group.key, right - left, bottom - top))
            continue
        found = next(
            (
                i
                for i, (label, box, _) in enumerate(regions)
                if label == group.label
                and all(box.contains(footprints[n], heading=24) for n in group.tables)
            ),
            None,
        )
        if found is None:
            raise ValueError("business regions")
        _, box, _ = regions.pop(found)
        centres[group.key] = (box.x + box.width / 2, box.y + box.height / 2)
        group_sizes.append((group.key, box.width, box.height))
    if regions:
        raise ValueError("business regions")
    routes = svg_routes(root)
    boundary_routes = [
        route
        for path, route in zip(
            (
                p
                for p in root.iter(NS + "path")
                if "connection" in p.get("class", "").split()
            ),
            routes,
            strict=True,
        )
        if path.get("data-erd-boundary") == "true"
    ]
    table_obstacles = [Rect(b.x, b.y, b.width, b.height) for b in boxes.values()]
    if any(
        not segment_clear(a, b, table_obstacles)
        for route in boundary_routes
        for a, b in pairwise(route)
    ):
        raise ValueError("route intersects a table")
    if any(
        not (
            bounds.x <= x <= bounds.x + bounds.width
            and bounds.y <= y <= bounds.y + bounds.height
        )
        for route in routes
        for x, y in route
    ):
        raise ValueError("clipped geometry")
    if len(routes) != sum(len(f.columns) for f in validation.relationships):
        raise ValueError("connection count")

    def at_field(point, name, column):
        box, height = boxes[name], headers[name]
        row = next(i for i, c in enumerate(schema[name].columns) if c.name == column)
        top = box.y + height * (row + 1)
        return (
            min(abs(point[0] - box.x), abs(point[0] - box.x - box.width)) <= 5
            and top + 1 < point[1] < top + height - 1
        )

    remaining = list(routes)
    for fk in validation.relationships:
        for local, remote in zip(fk.columns, fk.ref_columns, strict=True):
            # Pinned ELK self loops use table boundaries; retain that limitation.
            match = next(
                (
                    i
                    for i, route in enumerate(remaining)
                    if (
                        boxes[fk.table].at_border(route[0])
                        and boxes[fk.table].at_border(route[-1])
                        if fk.table == fk.ref_table
                        else at_field(route[0], fk.table, local)
                        and at_field(route[-1], fk.ref_table, remote)
                    )
                ),
                None,
            )
            if match is None:
                raise ValueError("field endpoints")
            remaining.pop(match)
    lengths = [path_length(route) for route in routes]
    crossings, crossing_points = _crossing_counts(routes)
    return LayoutMetrics(
        canvas[2],
        canvas[3],
        sum(b.width * b.height for b in footprints.values()),
        sum(lengths),
        max(lengths, default=0),
        crossings,
        weighted_distance(
            group_weights(
                {n: g.key for g in groups for n in g.tables}, validation.relationships
            ),
            centres,
        ),
        tuple(group_sizes),
        crossing_points,
    )
