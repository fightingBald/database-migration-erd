"""Anchor index captions inside space already reserved by the native layout.

Only caption x coordinates change. Tables, containers, routes, dimensions and
SQL-derived text remain untouched, including any TALA evaluation watermark.
"""

import math
from xml.dom import Node, minidom

SVG_NS = "http://www.w3.org/2000/svg"
HTML_NS = "http://www.w3.org/1999/xhtml"


def _children(node, tag):
    return [
        child
        for child in node.childNodes
        if child.nodeType == Node.ELEMENT_NODE
        and child.namespaceURI == SVG_NS
        and child.localName == tag
    ]


def _text(node):
    return "".join(
        child.data if child.nodeType == Node.TEXT_NODE else _text(child)
        for child in node.childNodes
    )


def _box(node):
    values = tuple(
        float(node.getAttribute(key)) for key in ("x", "y", "width", "height")
    )
    if not all(map(math.isfinite, values)) or min(values[2:]) <= 0:
        raise ValueError("index footer dimensions")
    return values


def align_index_captions(svg: str) -> str:
    """Keep each caption under its real table, independent of engine padding.

    Self loops can move a table within its invisible container. A fixed CSS
    indent cannot follow that movement. Read native geometry after layout and
    fail before publication if a caption cannot fit its reserved footprint.
    """
    if "data-erd-index-footer" not in svg:
        return svg
    with minidom.parseString(svg) as document:
        captions = []
        for label in document.getElementsByTagNameNS(SVG_NS, "foreignObject"):
            for content in label.getElementsByTagNameNS(HTML_NS, "div"):
                if content.getAttribute("data-erd-index-footer") == "true":
                    captions.append(
                        (label, content.getAttribute("data-erd-index-table"))
                    )
        if not captions:
            return svg
        tables = {}
        for header in document.getElementsByTagNameNS(SVG_NS, "rect"):
            if "class_header" not in header.getAttribute("class").split():
                continue
            group = header.parentNode
            texts = _children(group, "text")
            bodies = [
                rect
                for rect in _children(group, "rect")
                if "shape" in rect.getAttribute("class").split()
            ]
            if texts and len(bodies) == 1:
                name = _text(texts[0])
                if name in tables:
                    raise ValueError("index footer table anchor")
                tables[name] = _box(bodies[0])
        seen = set()
        for label, name in captions:
            if name not in tables or name in seen:
                raise ValueError("index footer table anchor")
            seen.add(name)
            table_x, table_y, table_width, table_height = tables[name]
            _, y, width, height = _box(label)
            rectangles = [
                rect
                for group in _children(label.parentNode.parentNode, "g")
                if group.getAttribute("class") == "shape"
                for rect in _children(group, "rect")
            ]
            if len(rectangles) != 1:
                raise ValueError("index footer container")
            x0, y0, w0, h0 = _box(rectangles[0])
            if not (
                x0 <= table_x
                and y0 <= table_y
                and table_x + table_width <= x0 + w0 + 1
                and y >= table_y + table_height
                and width <= table_width + 1
                and table_x + width <= x0 + w0 + 1
                and y + height <= y0 + h0 + 1
            ):
                raise ValueError("index footer bounds")
            label.setAttribute("x", f"{table_x:.6f}")
        return document.toxml()
