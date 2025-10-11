"""Build draw.io XML documents from schema metadata."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, Optional, Tuple
from xml.sax.saxutils import escape

from .layout import LayoutConfig, TableLayout, layout_tables
from .schema import Column, ForeignKey, Schema, Table


class IdGenerator:
    def __init__(self, start: int = 2) -> None:
        self._value = start

    def next(self) -> str:
        self._value += 1
        return f"mx{self._value}"


TABLE_STYLE = (
    "shape=table;startSize=30;container=1;collapsible=1;"
    "childLayout=tableLayout;fixedRows=1;rowLines=0;fontStyle=1;"
    "align=center;resizeLast=1;labelBackgroundColor=none;"
    "fillColor=#dae8fc;strokeColor=#6c8ebf;"
)
ROW_STYLE = (
    "shape=partialRectangle;collapsible=0;dropTarget=0;pointerEvents=0;"
    "fillColor=none;top=0;left=0;bottom=0;right=0;"
    "points=[[0,0.5],[1,0.5]];portConstraint=eastwest;"
    "strokeColor=#000000;"
)
CELL_LEFT_STYLE = (
    "shape=partialRectangle;connectable=0;fillColor=none;top=0;left=0;bottom=0;right=0;"
    "editable=1;overflow=hidden;fontStyle=1"
)
CELL_RIGHT_STYLE = (
    "shape=partialRectangle;connectable=1;fillColor=none;top=0;left=0;bottom=0;right=0;"
    "align=left;spacingLeft=6;overflow=hidden;portConstraint=eastwest;"
)
EDGE_STYLE = (
    "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;"
    "jettySize=auto;html=1;endArrow=block;strokeColor=#999999;"
)
NOTE_STYLE = (
    "text;html=1;align=left;verticalAlign=top;spacingLeft=4;"
    "spacingTop=4;strokeColor=none;fillColor=none;fontSize=12;"
)


def _render_table_label(table: Table) -> str:
    return escape(table.name.upper())


def _render_column_label(column: Column, show_types: bool) -> str:
    label = column.name.upper()
    if show_types and column.data_type:
        label = f"{label} ({column.data_type})"
    return escape(label)


def build_drawio(schema: Schema, show_types: bool = False, layout_config: LayoutConfig | None = None) -> ET.ElementTree:
    config = layout_config or LayoutConfig()
    layouts = layout_tables(schema, config)

    mxfile = ET.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "agent": "mxGraph",
            "version": "28.2.3",
        },
    )
    diagram = ET.SubElement(mxfile, "diagram", {"name": "Page-1", "id": "auto-gen"})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "1372",
            "dy": "773",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": "850",
            "pageHeight": "1100",
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    ids = IdGenerator()
    table_id_map: Dict[str, str] = {}
    column_cell_ids: Dict[Tuple[str, str], str] = {}

    for layout in layouts:
        table = layout.table
        total_height = layout.height + (layout.note_height if layout.note_lines else 0.0)

        group_id = ids.next()
        group_cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": group_id,
                "value": "",
                "style": "group",
                "vertex": "1",
                "connectable": "0",
                "parent": "1",
            },
        )
        ET.SubElement(
            group_cell,
            "mxGeometry",
            {
                "x": f"{layout.x:.2f}",
                "y": f"{layout.y:.2f}",
                "width": f"{layout.width:.2f}",
                "height": f"{max(total_height, 1.0):.2f}",
                "as": "geometry",
            },
        )

        table_id = ids.next()
        table_id_map[table.name] = table_id
        table_cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": table_id,
                "value": _render_table_label(table),
                "style": TABLE_STYLE,
                "vertex": "1",
                "parent": group_id,
            },
        )
        geometry = ET.SubElement(
            table_cell,
            "mxGeometry",
            {
                "x": "0",
                "y": "0",
                "width": f"{layout.width:.2f}",
                "height": f"{layout.height:.2f}",
                "as": "geometry",
            },
        )
        ET.SubElement(
            geometry,
            "mxRectangle",
            {
                "x": "80",
                "y": "10",
                "width": "50",
                "height": "30",
                "as": "alternateBounds",
            },
        )

        y_offset = config.header_height
        for index, column in enumerate(table.columns):
            row_id = ids.next()
            row_cell = ET.SubElement(
                root,
                "mxCell",
                {
                    "id": row_id,
                    "value": "",
                    "style": ROW_STYLE,
                    "vertex": "1",
                    "parent": table_id,
                },
            )
            ET.SubElement(
                row_cell,
                "mxGeometry",
                {
                    "y": f"{y_offset + index * config.row_height:.2f}",
                    "width": f"{layout.width:.2f}",
                    "height": f"{config.row_height:.2f}",
                    "as": "geometry",
                },
            )

            left_id = ids.next()
            left_label = "PK" if column.is_primary_key else ""
            left_style = CELL_LEFT_STYLE if left_label else CELL_LEFT_STYLE.replace("fontStyle=1", "")
            left_cell = ET.SubElement(
                root,
                "mxCell",
                {
                    "id": left_id,
                    "value": left_label,
                    "style": left_style,
                    "vertex": "1",
                    "parent": row_id,
                },
            )
            ET.SubElement(
                left_cell,
                "mxGeometry",
                {
                    "width": "30",
                    "height": f"{config.row_height:.2f}",
                    "as": "geometry",
                },
            )
            ET.SubElement(
                left_cell,
                "mxRectangle",
                {"width": "30", "height": f"{config.row_height:.2f}", "as": "alternateBounds"},
            )

            right_id = ids.next()
            right_cell = ET.SubElement(
                root,
                "mxCell",
                {
                    "id": right_id,
                    "value": _render_column_label(column, show_types),
                    "style": CELL_RIGHT_STYLE,
                    "vertex": "1",
                    "parent": row_id,
                },
            )
            ET.SubElement(
                right_cell,
                "mxGeometry",
                {
                    "x": "30",
                    "width": f"{layout.width - 30:.2f}",
                    "height": f"{config.row_height:.2f}",
                    "as": "geometry",
                },
            )
            ET.SubElement(
                right_cell,
                "mxRectangle",
                {
                    "width": f"{layout.width - 30:.2f}",
                    "height": f"{config.row_height:.2f}",
                    "as": "alternateBounds",
                },
            )
            column_cell_ids[(table.name, column.name.lower())] = right_id

        if layout.note_lines:
            margin = config.index_note_margin
            content_height = layout.note_height - margin
            note_value = "<br/>".join(escape(line) for line in layout.note_lines)
            note_id = ids.next()
            note_cell = ET.SubElement(
                root,
                "mxCell",
                {
                    "id": note_id,
                    "value": note_value,
                    "style": NOTE_STYLE,
                    "vertex": "1",
                    "parent": group_id,
                },
            )
            ET.SubElement(
                note_cell,
                "mxGeometry",
                {
                    "x": "0",
                    "y": f"{layout.height + margin:.2f}",
                    "width": f"{layout.width:.2f}",
                    "height": f"{max(content_height, 1.0):.2f}",
                    "as": "geometry",
                },
            )

    for table_name in sorted(schema.keys()):
        table = schema[table_name]
        source_id = table_id_map.get(table.name)
        if not source_id:
            continue
        for fk in table.foreign_keys:
            target_table_id = table_id_map.get(fk.ref_table)
            if not target_table_id:
                continue
            local_columns = list(fk.columns)
            ref_columns = list(fk.ref_columns)
            pairs: list[Tuple[str, Optional[str]]] = []
            if ref_columns and len(ref_columns) == len(local_columns):
                pairs = list(zip(local_columns, ref_columns))
            elif ref_columns:
                pairs = [(local_columns[0], ref_columns[0])]
            else:
                pairs = [(col, None) for col in local_columns]

            for local_col, ref_col in pairs:
                source_cell = column_cell_ids.get((table.name, local_col.lower()))
                target_cell = column_cell_ids.get((fk.ref_table, (ref_col or "").lower())) if ref_col else None
                if not target_cell and fk.ref_table in schema:
                    ref_table = schema[fk.ref_table]
                    candidates = []
                    if ref_col:
                        candidates.append(ref_col.lower())
                    candidates.append(local_col.lower())
                    candidates.extend(col.lower() for col in sorted(ref_table.primary_key))
                    for candidate in candidates:
                        hit = column_cell_ids.get((fk.ref_table, candidate))
                        if hit:
                            target_cell = hit
                            break

                source_ref = source_cell or source_id
                target_ref = target_cell or target_table_id
                edge_id = ids.next()
                edge_cell = ET.SubElement(
                    root,
                    "mxCell",
                    {
                        "id": edge_id,
                        "value": "",
                        "style": EDGE_STYLE,
                        "edge": "1",
                        "parent": "1",
                        "source": source_ref,
                        "target": target_ref,
                    },
                )
                ET.SubElement(edge_cell, "mxGeometry", {"relative": "1", "as": "geometry"})

    return ET.ElementTree(mxfile)
