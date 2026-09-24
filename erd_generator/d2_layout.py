"""Pure component grouping and estimated packing; D2/ELK places the actual shapes."""

import heapq
import math
from collections import deque
from dataclasses import dataclass

from .d2_dimensions import table_width
from .d2_grouping import centered_ranks, layout_ranks
from .d2_indexes import FOOTER_FONT_SIZE, footer_width, index_footer
from .d2_styles import COMPONENT_PADDING, GRID_GAP
from .schema import Schema, Table
from .validation import Relationship

TARGET_ASPECT = 1.4


@dataclass(frozen=True)
class Component:
    tables: tuple[str, ...]
    relationships: tuple[Relationship, ...]


def connected_components(
    schema: Schema,
    relationships: tuple[Relationship, ...],
    *,
    keep_together: tuple[tuple[str, ...], ...] = (),
) -> tuple[Component, ...]:
    """Keep real FKs and presentation membership inside one packed region.

    Membership joins affect adjacency only; returned relationships are always
    exactly the real, validated foreign keys.
    """
    neighbors = {name: set() for name in schema}
    for fk in relationships:
        neighbors[fk.table].add(fk.ref_table)
        neighbors[fk.ref_table].add(fk.table)
    for members in keep_together:
        for name in members[1:]:
            neighbors[members[0]].add(name)
            neighbors[name].add(members[0])
    visited = set()
    groups = []
    group_for_table = {}
    for name in sorted(schema):
        if name in visited:
            continue
        pending = [name]
        members = []
        visited.add(name)
        while pending:
            current = pending.pop()
            members.append(current)
            group_for_table[current] = len(groups)
            for neighbor in neighbors[current] - visited:
                visited.add(neighbor)
                pending.append(neighbor)
        groups.append(tuple(sorted(members)))
    edges: list[list[Relationship]] = [[] for _ in groups]
    for fk in sorted(relationships):
        edges[group_for_table[fk.table]].append(fk)
    return tuple(
        Component(names, tuple(fks)) for names, fks in zip(groups, edges, strict=True)
    )


def _table_size(
    table: Table, show_types: bool, show_indexes: bool = True
) -> tuple[int, int]:
    width = table_width(table, show_types)
    height = 36 * (len(table.columns) + 1)
    if show_indexes and (footer := index_footer(table, show_types)):
        width = max(width, footer_width(footer)) + 2 * COMPONENT_PADDING
        height += (
            int(1.5 * FOOTER_FONT_SIZE * len(footer.splitlines()))
            + 2 * COMPONENT_PADDING
        )
    return width, height


def table_ranks(
    component: Component,
    schema: Schema,
    show_types: bool,
    direction: str,
    *,
    center: bool = True,
    show_indexes: bool = True,
) -> dict[str, int]:
    """Center dominant tables only when estimated area and proportions improve.

    Compare two pure plans, without rendering or changing table dimensions. The
    existing colouring wins ties; small/dense graphs need no additional layers.
    """
    names = component.tables
    pairs = tuple((f.table, f.ref_table) for f in component.relationships)
    original = layout_ranks(names, pairs)
    if not center:
        return original
    neighbors = {n: set() for n in names}
    for a, b in pairs:
        if a != b:
            neighbors[a].add(b)
            neighbors[b].add(a)
    degree = max(map(len, neighbors.values()), default=0)
    if degree < 3:
        return original
    sizes = {n: _table_size(schema[n], show_types, show_indexes) for n in names}
    main, cross = (0, 1) if direction in {"right", "left"} else (1, 0)
    candidate = centered_ranks(
        names,
        pairs,
        hubs=tuple(n for n in names if len(neighbors[n]) == degree),
        weights={n: size[cross] for n, size in sizes.items()},
    )
    if candidate == original:
        return original

    def score(ranks: dict[str, int]) -> float:
        layers: dict[int, list[tuple[int, int]]] = {}
        for name in sorted(names):
            layers.setdefault(ranks[name], []).append(sizes[name])
        length = sum(max(s[main] for s in layer) for layer in layers.values())
        length += 70 * (len(layers) - 1)
        breadth = max(
            sum(s[cross] for s in layer) + 20 * (len(layer) - 1)
            for layer in layers.values()
        )
        # Penalize strips beyond the same preferred aspect used by packing.
        # This is a heuristic, not an ELK coordinate or canvas-ratio guarantee.
        return max(length * breadth, max(length, breadth) ** 2 / TARGET_ASPECT)

    return candidate if score(candidate) < score(original) else original


def _component_size(
    component: Component,
    schema: Schema,
    show_types: bool,
    direction: str,
    show_indexes: bool,
) -> tuple[int, int]:
    sizes = {
        name: _table_size(schema[name], show_types, show_indexes)
        for name in component.tables
    }
    neighbors = {name: set() for name in component.tables}
    outgoing = set()
    for fk in component.relationships:
        if fk.table != fk.ref_table:
            neighbors[fk.table].add(fk.ref_table)
            neighbors[fk.ref_table].add(fk.table)
            outgoing.add(fk.table)
    # A referenced root gives useful layer estimates for chains and stars. Cycles
    # use a stable fallback. This is a size estimate, never a replacement for ELK.
    roots = set(component.tables) - outgoing or set(component.tables)
    root = min(roots, key=lambda name: (-len(neighbors[name]), name))
    distance = {root: 0}
    pending = deque([root])
    while pending:
        name = pending.popleft()
        for neighbor in sorted(neighbors[name]):
            if neighbor not in distance:
                distance[neighbor] = distance[name] + 1
                pending.append(neighbor)
    layers: list[list[tuple[int, int]]] = [
        [] for _ in range(max(distance.values()) + 1)
    ]
    for name in component.tables:
        layers[distance[name]].append(sizes[name])
    horizontal = direction in {"right", "left"}
    main, cross = (0, 1) if horizontal else (1, 0)
    length = sum(max(size[main] for size in layer) for layer in layers)
    length += 70 * (len(layers) - 1)
    breadth = max(
        sum(size[cross] for size in layer) + 20 * (len(layer) - 1) for layer in layers
    )
    width, height = (length, breadth) if horizontal else (breadth, length)
    if any(fk.table == fk.ref_table for fk in component.relationships):
        width += 100
        height += 40
    return width + 2 * COMPONENT_PADDING, height + 2 * COMPONENT_PADDING


def plan_layout(
    schema: Schema,
    relationships: tuple[Relationship, ...],
    *,
    show_types: bool,
    direction: str,
    keep_together: tuple[tuple[str, ...], ...] = (),
    show_indexes: bool = True,
) -> tuple[tuple[Component, ...], ...]:
    """Choose columns by estimated aspect ratio and wasted area, without I/O.

    Validation belongs to the caller. Output order is independent of input order.
    Natural table dimensions and all connection routing remain D2/ELK's job.
    """
    components = connected_components(
        schema, relationships, keep_together=keep_together
    )
    if len(components) <= 1:
        return (components,)
    return _pack(
        [
            (
                component,
                *estimate_size(
                    component, schema, show_types, direction, show_indexes=show_indexes
                ),
            )
            for component in components
        ]
    )


def estimate_size(
    component: Component,
    schema: Schema,
    show_types: bool,
    direction: str,
    *,
    show_indexes: bool = True,
) -> tuple[int, int]:
    """Estimate a region which may join otherwise disconnected business tables."""
    parts = connected_components(
        {n: schema[n] for n in component.tables}, component.relationships
    )
    if len(parts) == 1:
        return _component_size(component, schema, show_types, direction, show_indexes)
    sizes = {
        part.tables: _component_size(part, schema, show_types, direction, show_indexes)
        for part in parts
    }
    packed = _pack([(part, *sizes[part.tables]) for part in parts])
    width = sum(max(sizes[part.tables][0] for part in col) for col in packed)
    height = max(
        sum(sizes[part.tables][1] for part in col) + GRID_GAP * (len(col) - 1)
        for col in packed
    )
    return width + GRID_GAP * (len(packed) - 1), height + 2 * GRID_GAP


def _pack(items: list[tuple[Component, int, int]]) -> tuple[tuple[Component, ...], ...]:
    """Pack estimated rectangles; shared by legacy and business-region planning."""
    packed = pack_sizes(
        [(component.tables, width, height) for component, width, height in items]
    )
    by_tables = {component.tables: component for component, _, _ in items}
    return tuple(tuple(by_tables[tables] for tables in column) for column in packed)


def pack_sizes(
    items: list[tuple[tuple[str, ...], float, float]],
) -> tuple[tuple[tuple[str, ...], ...], ...]:
    """Pack estimated rectangles into balanced columns.

    The keys may represent tables or already-laid-out business clusters. Keeping
    this primitive independent from SQL relationships enables the second layout
    level to treat a cluster as one super-node.
    """
    items = list(items)
    items.sort(key=lambda item: (-item[2], -item[1], item[0]))
    area = sum(width * height for _, width, height in items)
    best_score = math.inf
    best: tuple[tuple[tuple[str, ...], ...], ...] = ()
    for count in range(1, len(items) + 1):
        columns: list[list[tuple[str, ...]]] = [[] for _ in range(count)]
        widths = [0] * count
        heights = [0] * count
        queue = [(0, i) for i in range(count)]
        for key, width, height in items:
            current_height, index = heapq.heappop(queue)
            heights[index] = current_height + height
            widths[index] = max(widths[index], width)
            columns[index].append(key)
            heapq.heappush(queue, (heights[index] + GRID_GAP, index))
        width = sum(widths) + GRID_GAP * (count - 1)
        height = max(heights) + 2 * GRID_GAP  # Padding inside invisible columns.
        aspect = (width + 200) / (height + 200)  # Renderer canvas padding.
        score = abs(math.log(aspect / TARGET_ASPECT)) + 0.75 * math.log(
            width * height / area
        )
        if score < best_score:
            best_score = score
            best = tuple(tuple(column) for column in columns)
    return best
