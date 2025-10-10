
"""Layout helpers deciding where each table should be rendered."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List

import networkx as nx

from .schema import Schema, Table, describe_table_notes


@dataclass(frozen=True)
class LayoutConfig:
    per_row: int = 0
    table_width: int = 340
    row_height: int = 30
    header_height: int = 30
    padding_x: int = 120
    padding_y: int = 60
    gap_x: int = 140
    gap_y: int = 120
    index_note_margin: int = 12
    index_note_line_height: int = 16


@dataclass
class TableLayout:
    table: Table
    x: float
    y: float
    width: float
    height: float
    note_lines: List[str]
    note_height: float

    @property
    def total_rows(self) -> int:
        return max(1, len(self.table.columns))


def calculate_table_height(table: Table, config: LayoutConfig) -> float:
    rows = max(1, len(table.columns))
    return config.header_height + rows * config.row_height


def calculate_note_height(table: Table, config: LayoutConfig) -> tuple[List[str], float]:
    lines = describe_table_notes(table)
    if not lines:
        return [], 0.0
    content_height = len(lines) * config.index_note_line_height
    return lines, float(config.index_note_margin + content_height)


def _build_levels(schema: Schema) -> Dict[str, int]:
    graph = nx.DiGraph()
    graph.add_nodes_from(schema.keys())
    for table_name, table in schema.items():
        for fk in table.foreign_keys:
            if fk.ref_table in schema:
                graph.add_edge(fk.ref_table, table_name)

    levels: Dict[str, int] = {}
    if not graph.nodes:
        return levels

    if nx.is_directed_acyclic_graph(graph):
        for depth, layer in enumerate(nx.topological_generations(graph)):
            for node in sorted(layer):
                levels[node] = depth
    else:
        condensation = nx.condensation(graph)
        for depth, layer in enumerate(nx.topological_generations(condensation)):
            members: List[str] = []
            for component in layer:
                members.extend(condensation.nodes[component]["members"])
            for node in sorted(members):
                levels[node] = depth
    for node in graph.nodes:
        levels.setdefault(node, 0)
    return levels


def layout_tables(schema: Schema, config: LayoutConfig | None = None) -> List[TableLayout]:
    if config is None:
        config = LayoutConfig()

    if not schema:
        return []

    table_heights: Dict[str, float] = {
        name: calculate_table_height(table, config) for name, table in schema.items()
    }
    note_info: Dict[str, tuple[List[str], float]] = {
        name: calculate_note_height(table, config) for name, table in schema.items()
    }

    levels = _build_levels(schema)
    tables_by_level: Dict[int, List[str]] = {}
    for name, level in levels.items():
        tables_by_level.setdefault(level, []).append(name)

    auto_per_row = max(1, int(math.sqrt(len(schema))))
    chunk_size = config.per_row if config.per_row > 0 else auto_per_row

    ordered_rows: List[List[str]] = []
    for level in sorted(tables_by_level.keys()):
        names = sorted(tables_by_level[level])
        for idx in range(0, len(names), chunk_size):
            ordered_rows.append(names[idx : idx + chunk_size])

    if not ordered_rows:
        return []

    row_widths: List[float] = []
    for row in ordered_rows:
        count = len(row)
        row_width = config.table_width * count + config.gap_x * max(0, count - 1)
        row_widths.append(row_width)
    max_row_width = max(row_widths)

    layouts: List[TableLayout] = []
    current_y = float(config.padding_y)

    for row, row_width in zip(ordered_rows, row_widths):
        row_height = max(table_heights[name] + note_info[name][1] for name in row)
        start_x = config.padding_x + (max_row_width - row_width) / 2
        for col_index, table_name in enumerate(row):
            x = float(start_x + col_index * (config.table_width + config.gap_x))
            table = schema[table_name]
            note_lines, note_height = note_info[table_name]
            layouts.append(
                TableLayout(
                    table=table,
                    x=x,
                    y=current_y,
                    width=float(config.table_width),
                    height=table_heights[table_name],
                    note_lines=note_lines,
                    note_height=note_height,
                )
            )
        current_y += row_height + config.gap_y

    return layouts
