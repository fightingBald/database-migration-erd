"""Pure component grouping and estimated packing; D2/ELK places the actual shapes."""

from collections import deque
from dataclasses import dataclass
import heapq
import math
import unicodedata

from .schema import Schema, Table
from .d2_styles import COMPONENT_PADDING, GRID_GAP
from .validation import Relationship

TARGET_ASPECT = 1.4


@dataclass(frozen=True)
class Component:
    tables: tuple[str, ...]
    relationships: tuple[Relationship, ...]


def connected_components(
    schema: Schema, relationships: tuple[Relationship, ...]
) -> tuple[Component, ...]:
    """Use undirected connectivity; every FK remains inside one component."""
    neighbors = {name: set() for name in schema}
    for fk in relationships:
        neighbors[fk.table].add(fk.ref_table)
        neighbors[fk.ref_table].add(fk.table)
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
    return tuple(Component(names, tuple(fks)) for names, fks in zip(groups, edges))


def _text_width(text: str) -> int:
    return max(
        (
            sum(
                0
                if unicodedata.combining(char)
                else 2
                if unicodedata.east_asian_width(char) in {"W", "F"}
                else 1
                for char in line
            )
            for line in text.splitlines()
        ),
        default=0,
    )


def _table_size(table: Table, show_types: bool) -> tuple[int, int]:
    names = max((_text_width(c.name) for c in table.columns), default=0)
    types = (
        max((_text_width(c.data_type) for c in table.columns), default=0)
        if show_types
        else 0
    )
    width = max(180, 20 + 11 * _text_width(table.name), 80 + 10 * (names + types))
    return width, 36 * (len(table.columns) + 1)


def _component_size(
    component: Component, schema: Schema, show_types: bool, direction: str
) -> tuple[int, int]:
    sizes = {name: _table_size(schema[name], show_types) for name in component.tables}
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
) -> tuple[tuple[Component, ...], ...]:
    """Choose columns by estimated aspect ratio and wasted area, without I/O.

    Validation belongs to the caller. Output order is independent of input order.
    Natural table dimensions and all connection routing remain D2/ELK's job.
    """
    components = connected_components(schema, relationships)
    if len(components) <= 1:
        return (components,)
    items = [
        (component, *_component_size(component, schema, show_types, direction))
        for component in components
    ]
    items.sort(key=lambda item: (-item[2], -item[1], item[0].tables))
    area = sum(width * height for _, width, height in items)
    best_score = math.inf
    best = ()
    for count in range(1, len(items) + 1):
        columns: list[list[Component]] = [[] for _ in range(count)]
        widths = [0] * count
        heights = [0] * count
        queue = [(0, i) for i in range(count)]
        for component, width, height in items:
            current_height, index = heapq.heappop(queue)
            heights[index] = current_height + height
            widths[index] = max(widths[index], width)
            columns[index].append(component)
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
