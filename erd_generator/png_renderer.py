"""Render ER diagrams to simple PNG images and embed draw.io metadata."""
from __future__ import annotations

import base64
import math
import os
import zlib
from dataclasses import dataclass
from typing import Iterable, Sequence

from .layout import LayoutConfig, TableLayout, layout_tables
from .schema import Column, Schema


@dataclass(frozen=True)
class RGB:
    r: int
    g: int
    b: int

    @classmethod
    def from_hex(cls, value: str) -> "RGB":
        value = value.lstrip("#")
        return cls(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


BACKGROUND = RGB(255, 255, 255)
TABLE_FILL = RGB.from_hex("#dae8fc")
TABLE_BORDER = RGB.from_hex("#6c8ebf")
ROW_BORDER = RGB.from_hex("#999999")
TEXT_COLOR = RGB(0, 0, 0)
HEADER_TEXT = RGB(40, 40, 40)
NOTE_TEXT = RGB(55, 55, 55)

SCALE = 2
LEFT_CELL_WIDTH = 30
HEADER_PADDING_Y = 8
TEXT_PADDING_X = 6
ROW_TEXT_PADDING_Y = 8
NOTE_LINE_SPACING = 4

FONT_WIDTH = 5
FONT_HEIGHT = 7

FONT_MAP = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "11110", "10001", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "11110", "10000", "10000", "10000", "11111"),
    "F": ("11111", "10000", "11110", "10000", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "11111", "10001", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("11111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "11100", "10100", "11010", "10001", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "00110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "11100"),
    " ": ("00000",) * FONT_HEIGHT,
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
    ":": ("00000", "00100", "00000", "00000", "00000", "00100", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00100", "00000"),
    ",": ("00000", "00000", "00000", "00000", "00000", "00100", "01000"),
    "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
    ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
    "/": ("00001", "00010", "00100", "01000", "10000", "00000", "00000"),
    "'": ("00100", "00100", "00000", "00000", "00000", "00000", "00000"),
    "#": ("01010", "11111", "01010", "01010", "11111", "01010", "01010"),
    "&": ("01100", "10000", "10100", "01000", "10101", "10010", "01101"),
    "=": ("00000", "11111", "00000", "11111", "00000", "00000", "00000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "<": ("00010", "00100", "01000", "10000", "01000", "00100", "00010"),
    ">": ("01000", "00100", "00010", "00001", "00010", "00100", "01000"),
    "?": ("01110", "10001", "00010", "00100", "00100", "00000", "00100"),
    "%": ("10001", "10010", "00100", "01000", "10010", "10001", "00000"),
}

DEFAULT_GLYPH = FONT_MAP["?"]


class Canvas:
    def __init__(self, width: int, height: int, background: RGB = BACKGROUND) -> None:
        self.width = width
        self.height = height
        self.pixels = bytearray(width * height * 3)
        self._fill_background(background)

    def _fill_background(self, color: RGB) -> None:
        r, g, b = color.r, color.g, color.b
        for i in range(0, len(self.pixels), 3):
            self.pixels[i] = r
            self.pixels[i + 1] = g
            self.pixels[i + 2] = b

    def set_pixel(self, x: int, y: int, color: RGB) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            idx = (y * self.width + x) * 3
            self.pixels[idx] = color.r
            self.pixels[idx + 1] = color.g
            self.pixels[idx + 2] = color.b

    def fill_rect(self, x0: int, y0: int, x1: int, y1: int, color: RGB) -> None:
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(self.width, x1), min(self.height, y1)
        if x0 >= x1 or y0 >= y1:
            return
        r, g, b = color.r, color.g, color.b
        row_bytes = self.width * 3
        for y in range(y0, y1):
            start = y * row_bytes + x0 * 3
            for offset in range(0, (x1 - x0) * 3, 3):
                idx = start + offset
                self.pixels[idx] = r
                self.pixels[idx + 1] = g
                self.pixels[idx + 2] = b

    def draw_hline(self, x0: int, x1: int, y: int, color: RGB) -> None:
        if 0 <= y < self.height:
            for x in range(max(0, x0), min(self.width, x1)):
                self.set_pixel(x, y, color)

    def draw_vline(self, x: int, y0: int, y1: int, color: RGB) -> None:
        if 0 <= x < self.width:
            for y in range(max(0, y0), min(self.height, y1)):
                self.set_pixel(x, y, color)

    def draw_rect_outline(self, x0: int, y0: int, x1: int, y1: int, color: RGB) -> None:
        self.draw_hline(x0, x1, y0, color)
        self.draw_hline(x0, x1, y1 - 1, color)
        self.draw_vline(x0, y0, y1, color)
        self.draw_vline(x1 - 1, y0, y1, color)

    def draw_text(self, x: int, y: int, text: str, color: RGB, scale: int = 2) -> None:
        cursor_x = x
        cursor_y = y
        line_height = (FONT_HEIGHT * scale) + NOTE_LINE_SPACING
        for line in text.splitlines():
            for ch in line:
                glyph = FONT_MAP.get(ch, DEFAULT_GLYPH)
                self._blit_glyph(cursor_x, cursor_y, glyph, color, scale)
                cursor_x += (FONT_WIDTH + 1) * scale
            cursor_x = x
            cursor_y += line_height

    def _blit_glyph(self, x: int, y: int, glyph: Sequence[str], color: RGB, scale: int) -> None:
        for row_idx, row in enumerate(glyph):
            for col_idx, bit in enumerate(row):
                if bit == "1":
                    for sy in range(scale):
                        for sx in range(scale):
                            self.set_pixel(x + col_idx * scale + sx, y + row_idx * scale + sy, color)


def _chunk(tag: bytes, data: bytes) -> bytes:
    length = len(data)
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return length.to_bytes(4, "big") + tag + data + crc.to_bytes(4, "big")


def _itxt_chunk(keyword: str, text: bytes, *, compressed: bool) -> bytes:
    keyword_bytes = keyword.encode("latin-1")
    language_tag = b""
    translated_keyword = b""
    if compressed:
        compression_flag = b"\x01"
        payload = zlib.compress(text, 9)
    else:
        compression_flag = b"\x00"
        payload = text
    compression_method = b"\x00"
    data = (
        keyword_bytes
        + b"\x00"
        + compression_flag
        + compression_method
        + language_tag
        + b"\x00"
        + translated_keyword
        + b"\x00"
        + payload
    )
    return _chunk(b"iTXt", data)


def save_png(path: str, width: int, height: int, pixels: bytes, xml: str | None = None) -> None:
    raw = bytearray()
    row_bytes = width * 3
    for y in range(height):
        raw.append(0)
        start = y * row_bytes
        raw.extend(pixels[start : start + row_bytes])
    compressed = zlib.compress(bytes(raw), 9)

    metadata_chunks: list[bytes] = []
    if xml:
        xml_bytes = xml.encode("utf-8")
        metadata_chunks.append(_itxt_chunk("mxGraphModel", xml_bytes, compressed=True))
        encoded = base64.b64encode(zlib.compress(xml_bytes, 9))
        metadata_chunks.append(_itxt_chunk("mxfile", encoded, compressed=False))

    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n")
        handle.write(
            _chunk(
                b"IHDR",
                width.to_bytes(4, "big")
                + height.to_bytes(4, "big")
                + b"\x08\x02\x00\x00\x00",
            )
        )
        for chunk in metadata_chunks:
            handle.write(chunk)
        handle.write(_chunk(b"IDAT", compressed))
        handle.write(_chunk(b"IEND", b""))


def _compute_canvas_dimensions(layouts: Sequence[TableLayout], config: LayoutConfig) -> tuple[int, int]:
    if not layouts:
        width = int(config.padding_x * SCALE * 2)
        height = int(config.padding_y * SCALE * 2)
        return max(width, 1), max(height, 1)
    max_x = max(layout.x + layout.width for layout in layouts)
    max_y = max(layout.y + layout.height + layout.note_height for layout in layouts)
    width = int(math.ceil((max_x + config.padding_x) * SCALE))
    height = int(math.ceil((max_y + config.padding_y) * SCALE))
    return max(width, 1), max(height, 1)


def _render_table(canvas: Canvas, layout: TableLayout, config: LayoutConfig, show_types: bool) -> None:
    table = layout.table
    x = int(round(layout.x * SCALE))
    y = int(round(layout.y * SCALE))
    width = int(round(layout.width * SCALE))
    height = int(round(layout.height * SCALE))
    header_height = int(round(config.header_height * SCALE))
    row_height = int(round(config.row_height * SCALE))
    left_width = int(round(LEFT_CELL_WIDTH * SCALE))

    canvas.fill_rect(x, y, x + width, y + height, TABLE_FILL)
    canvas.draw_rect_outline(x, y, x + width, y + height, TABLE_BORDER)
    canvas.draw_hline(x, x + width, y + header_height, TABLE_BORDER)

    header_text = table.name.upper()
    text_x = x + TEXT_PADDING_X
    text_y = y + HEADER_PADDING_Y
    canvas.draw_text(text_x, text_y, header_text, HEADER_TEXT, scale=2)

    for idx, column in enumerate(table.columns):
        row_top = y + header_height + idx * row_height
        canvas.draw_hline(x, x + width, row_top, ROW_BORDER)
        row_bottom = row_top + row_height
        canvas.fill_rect(x, row_top, x + left_width, row_bottom, TABLE_FILL)
        canvas.draw_vline(x + left_width, row_top, row_bottom, ROW_BORDER)

        pk_label = "PK" if column.is_primary_key else ""
        if pk_label:
            canvas.draw_text(x + TEXT_PADDING_X, row_top + ROW_TEXT_PADDING_Y, pk_label, TEXT_COLOR, scale=2)

        column_label = _column_label(column, show_types)
        canvas.draw_text(
            x + left_width + TEXT_PADDING_X,
            row_top + ROW_TEXT_PADDING_Y,
            column_label,
            TEXT_COLOR,
            scale=2,
        )

    canvas.draw_hline(x, x + width, y + height, ROW_BORDER)

    if layout.note_lines:
        note_text = "\n".join(line.upper() for line in layout.note_lines)
        note_y = int(round((layout.y + layout.height + config.index_note_margin) * SCALE))
        canvas.draw_text(x, note_y, note_text, NOTE_TEXT, scale=2)


def _column_label(column: Column, show_types: bool) -> str:
    if show_types and column.data_type:
        return f"{column.name.upper()} ({column.data_type})"
    return column.name.upper()


def render_png(
    schema: Schema,
    path: str,
    *,
    show_types: bool = False,
    layout_config: LayoutConfig | None = None,
    embedded_xml: str | None = None,
) -> None:
    if layout_config is None:
        layout_config = LayoutConfig()
    layouts = layout_tables(schema, layout_config)
    width, height = _compute_canvas_dimensions(layouts, layout_config)
    canvas = Canvas(width, height, BACKGROUND)
    for layout in layouts:
        _render_table(canvas, layout, layout_config, show_types)

    output_dir = os.path.dirname(os.path.abspath(path))
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    save_png(path, canvas.width, canvas.height, bytes(canvas.pixels), xml=embedded_xml)
