"""Conservative text and table dimensions for native D2 layout hints."""

import unicodedata

from .schema import Table


def text_width(text: str) -> int:
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


def table_width(table: Table, show_types: bool) -> int:
    names = max((text_width(c.name) for c in table.columns), default=0)
    types = (
        max((text_width(c.data_type) for c in table.columns), default=0)
        if show_types
        else 0
    )
    return max(180, 20 + 11 * text_width(table.name), 80 + 10 * (names + types))
