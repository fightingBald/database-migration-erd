"""Layout helpers deciding where each table should be rendered."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .schema import Schema, Table


@dataclass(frozen=True)
class LayoutConfig:
    per_row: int = 3
    table_width: int = 290
    row_height: int = 30
    header_height: int = 30
    padding_x: int = 80
    padding_y: int = 40
    gap_x: int = 60
    gap_y: int = 60


@dataclass
class TableLayout:
    table: Table
    x: float
    y: float
    width: float
    height: float

    @property
    def total_rows(self) -> int:
        return max(1, len(self.table.columns))


def calculate_table_height(table: Table, config: LayoutConfig) -> float:
    rows = max(1, len(table.columns))
    return config.header_height + rows * config.row_height


def layout_tables(schema: Schema, config: LayoutConfig | None = None) -> List[TableLayout]:
    if config is None:
        config = LayoutConfig()

    table_names = sorted(schema.keys())
    if not table_names:
        return []

    table_heights: Dict[str, float] = {
        name: calculate_table_height(schema[name], config) for name in table_names
    }

    layouts: List[TableLayout] = []
    current_y = float(config.padding_y)
    per_row = max(1, config.per_row)

    for row_start in range(0, len(table_names), per_row):
        row_tables = table_names[row_start : row_start + per_row]
        row_height = max(table_heights[name] for name in row_tables)
        for col_index, table_name in enumerate(row_tables):
            x = float(config.padding_x + col_index * (config.table_width + config.gap_x))
            table = schema[table_name]
            layouts.append(
                TableLayout(
                    table=table,
                    x=x,
                    y=current_y,
                    width=float(config.table_width),
                    height=table_heights[table_name],
                )
            )
        current_y += row_height + config.gap_y

    return layouts
