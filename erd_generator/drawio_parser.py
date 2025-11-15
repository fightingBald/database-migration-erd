"""Utilities to parse draw.io XML files and extract table/column edges."""
from __future__ import annotations

import html
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple
import xml.etree.ElementTree as ET

LABEL_TOKENS = {"pk", "fk"}
MAX_SEARCH_DEPTH = 6
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def _clean_value(value: Optional[str]) -> str:
    if not value:
        return ""
    text = html.unescape(value)
    text = TAG_RE.sub(" ", text)
    text = SPACE_RE.sub(" ", text)
    return text.strip()


def _style_contains(style: Optional[str], fragment: str) -> bool:
    if not style:
        return False
    return fragment.lower() in style.lower()


@dataclass
class Cell:
    id: str
    value: str
    raw_value: str
    style: Optional[str]
    vertex: bool
    edge: bool
    parent: Optional[str]
    source: Optional[str]
    target: Optional[str]


@dataclass(frozen=True)
class ColumnContext:
    table: str
    column: str


@dataclass
class DiagramTable:
    name: str
    columns: List[str]
    note_lines: List[str]


def _iter_cells(tree_root: ET.Element) -> Iterable[Cell]:
    for cell in tree_root.iter("mxCell"):
        cell_id = cell.attrib.get("id")
        if not cell_id:
            continue
        raw_value = cell.attrib.get("value", "")
        yield Cell(
            id=cell_id,
            value=_clean_value(raw_value),
            raw_value=raw_value,
            style=cell.attrib.get("style"),
            vertex=cell.attrib.get("vertex") == "1",
            edge=cell.attrib.get("edge") == "1",
            parent=cell.attrib.get("parent"),
            source=cell.attrib.get("source"),
            target=cell.attrib.get("target"),
        )


def _value_is_label(value: str) -> bool:
    if not value:
        return True
    normalized = value.strip().lower()
    return normalized in LABEL_TOKENS


def _find_table_ancestor(
    cell_id: Optional[str],
    cells: Dict[str, Cell],
    table_ids: Dict[str, str],
) -> Optional[str]:
    seen: set[str] = set()
    current = cell_id
    while current:
        if current in seen:
            break
        seen.add(current)
        if current in table_ids:
            return current
        cell = cells.get(current)
        if cell is None or not cell.parent:
            break
        current = cell.parent
    return None


def _resolve_column_name(
    start_id: str,
    table_id: str,
    cells: Dict[str, Cell],
    children: Dict[str, List[str]],
) -> str:
    queue = deque([(start_id, 0)])
    visited: set[str] = set()
    while queue:
        node_id, depth = queue.popleft()
        if node_id in visited or depth > MAX_SEARCH_DEPTH:
            continue
        visited.add(node_id)
        node = cells.get(node_id)
        if node is None:
            continue
        if node.value and not _value_is_label(node.value):
            return node.value
        for child_id in children.get(node_id, []):
            if child_id not in visited:
                queue.append((child_id, depth + 1))
        parent_id = node.parent
        if not parent_id or parent_id == table_id:
            continue
        if parent_id not in visited:
            queue.append((parent_id, depth + 1))
        for sibling_id in children.get(parent_id, []):
            if sibling_id == node_id or sibling_id in visited:
                continue
            queue.append((sibling_id, depth + 1))
    return ""


def _resolve_node_context(
    start_id: Optional[str],
    table_ids: Dict[str, str],
    column_map: Dict[str, ColumnContext],
    cells: Dict[str, Cell],
) -> Optional[ColumnContext]:
    current = start_id
    visited: set[str] = set()
    while current:
        if current in visited:
            break
        visited.add(current)
        if current in table_ids:
            return ColumnContext(table=table_ids[current], column="")
        if current in column_map:
            return column_map[current]
        cell = cells.get(current)
        if cell is None or not cell.parent:
            break
        current = cell.parent
    return None


def _extract_note_lines(raw_value: str) -> List[str]:
    if not raw_value:
        return []
    text = raw_value
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</div>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<div[^>]*>", "", text, flags=re.IGNORECASE)
    text = html.unescape(text)
    text = TAG_RE.sub(" ", text)
    lines = [line.strip() for line in text.splitlines()]
    return [line for line in lines if line]


def parse_drawio_edges(path: str) -> List[Dict[str, str]]:
    """Parse a .drawio XML file and return edge mappings between tables/columns."""
    tree = ET.parse(path)
    root = tree.getroot()
    cells = {cell.id: cell for cell in _iter_cells(root)}
    children: Dict[str, List[str]] = defaultdict(list)
    for cell in cells.values():
        if cell.parent:
            children[cell.parent].append(cell.id)

    table_ids: Dict[str, str] = {}
    for cell in cells.values():
        if cell.vertex and _style_contains(cell.style, "shape=table") and cell.value:
            table_ids[cell.id] = cell.value

    column_map: Dict[str, ColumnContext] = {}
    for cell_id, cell in cells.items():
        if cell.edge or cell_id in table_ids:
            continue
        if cell.style and cell.style.strip().lower().startswith("text;"):
            continue
        table_id = _find_table_ancestor(cell_id, cells, table_ids)
        if not table_id:
            continue
        column_name = _resolve_column_name(cell_id, table_id, cells, children)
        column_map[cell_id] = ColumnContext(table=table_ids[table_id], column=column_name)

    edges: List[Dict[str, str]] = []
    for cell in cells.values():
        if not cell.edge:
            continue
        start = _resolve_node_context(cell.source, table_ids, column_map, cells)
        end = _resolve_node_context(cell.target, table_ids, column_map, cells)
        edges.append(
            {
                "start_table": start.table if start else "",
                "start_column": start.column if start else "",
                "end_table": end.table if end else "",
                "end_column": end.column if end else "",
            }
        )
    return edges


def parse_drawio_tables(path: str) -> Dict[str, DiagramTable]:
    """Parse a .drawio XML file and return table/column/note metadata."""
    tree = ET.parse(path)
    root = tree.getroot()
    cells = {cell.id: cell for cell in _iter_cells(root)}
    children: Dict[str, List[str]] = defaultdict(list)
    for cell in cells.values():
        if cell.parent:
            children[cell.parent].append(cell.id)

    table_ids: Dict[str, str] = {}
    group_map: Dict[str, str] = {}
    for cell in cells.values():
        if cell.vertex and _style_contains(cell.style, "shape=table") and cell.value:
            table_ids[cell.id] = cell.value
            if cell.parent:
                group_map[cell.parent] = cell.value

    column_map: Dict[str, ColumnContext] = {}
    for cell_id, cell in cells.items():
        if cell.edge or cell_id in table_ids:
            continue
        if cell.style and cell.style.strip().lower().startswith("text;"):
            continue
        table_id = _find_table_ancestor(cell_id, cells, table_ids)
        if not table_id:
            continue
        column_name = _resolve_column_name(cell_id, table_id, cells, children)
        column_map[cell_id] = ColumnContext(table=table_ids[table_id], column=column_name)

    table_columns: Dict[str, List[str]] = {}
    seen_columns: Dict[str, set[str]] = defaultdict(set)
    for context in column_map.values():
        column = context.column
        if not column:
            continue
        normalized = column.lower()
        recorded = seen_columns[context.table]
        if normalized in recorded:
            continue
        recorded.add(normalized)
        table_columns.setdefault(context.table, []).append(column)

    note_lines: Dict[str, List[str]] = defaultdict(list)
    for cell in cells.values():
        if not cell.style or not cell.style.strip().lower().startswith("text;"):
            continue
        table_name = group_map.get(cell.parent or "")
        if not table_name:
            continue
        lines = _extract_note_lines(cell.raw_value)
        if lines:
            note_lines[table_name].extend(lines)

    tables: Dict[str, DiagramTable] = {}
    for table_name in table_ids.values():
        tables[table_name] = DiagramTable(
            name=table_name,
            columns=table_columns.get(table_name, []),
            note_lines=note_lines.get(table_name, []),
        )
    return tables


__all__ = ["parse_drawio_edges", "parse_drawio_tables", "DiagramTable"]
