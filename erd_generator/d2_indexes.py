"""Pure index descriptions shared by D2 output, sizing and verification."""

import html
import textwrap

from .d2_dimensions import table_width, text_width
from .schema import Index, Table

FOOTER_FONT_SIZE = 12
FOOTER_STYLE = (
    f"text-align:left;font-size:{FOOTER_FONT_SIZE}px;"
    "color:#475569;line-height:1.5;white-space:pre"
)
TABLE_BODY_KEY = "_erd_table"


def sorted_indexes(table: Table) -> list[Index]:
    return sorted(
        table.indexes,
        key=lambda i: (
            i.name or "",
            i.columns,
            i.unique,
            i.method or "",
            i.where or "",
        ),
    )


def index_footer(table: Table, show_types: bool = False) -> str:
    """Wrap plain text without dropping SQL tokens or truncating identifiers.

    This becomes a native container label, not extra SQL-table rows. Keep the full
    unwrapped metadata in the table tooltip as well.
    """
    lines = []
    width = max(24, table_width(table, show_types) // 7)
    for index in sorted_indexes(table):
        label = "UNIQUE" if index.unique else "INDEX"
        name = f" {index.name}" if index.name else ""
        method = f" USING {index.method}" if index.method else ""
        heading = f"{label}{name}"
        details = f"{method} ({', '.join(index.columns)})"
        if index.where:
            details += f" WHERE {index.where}"
        description = heading + details
        if text_width(description) <= width:
            lines.append(description)
            continue
        # Names are atomic, including quoted identifiers containing whitespace.
        # Put the definition below the name instead of slicing the identifier.
        lines.append(heading)
        lines.extend(
            textwrap.wrap(
                details,
                width=width,
                expand_tabs=False,
                replace_whitespace=False,
                drop_whitespace=False,
                break_on_hyphens=False,
                break_long_words=False,
            )
        )
    return "\n".join(lines)


def footer_width(text: str) -> int:
    """Reserve native table width for a caption before routing foreign keys.

    Uppercase and wide Latin glyphs need more space than ordinary lowercase
    text. D2 still measures the real font; the renderer checks the final fit.
    """
    return (
        max(
            (
                sum(
                    text_width(char)
                    * (12 if char in "MWmw@%" else 9 if char.isupper() else 7)
                    for char in line
                )
                for line in text.splitlines()
            ),
            default=0,
        )
        + 8
    )


def footer_markup(text: str, table_name: str | None = None) -> str:
    """A native D2 Markdown label with independently left-aligned lines.

    Escape HTML and D2 block/interpolation syntax before inserting SQL-derived
    text. Span markers also let SVG verification check the visible label.
    """
    lines = [
        html.escape(line).replace("|", "&#124;").replace("$", "&#36;")
        for line in text.splitlines()
    ]
    content = "<br/>".join(
        f'<span data-erd-index-line="true">{line}</span>' for line in lines
    )
    anchor = (
        f' data-erd-index-table="{html.escape(table_name, quote=True).replace("|", "&#124;").replace("$", "&#36;")}"'
        if table_name is not None
        else ""
    )
    return f'<div data-erd-index-footer="true"{anchor} style="{FOOTER_STYLE}">{content}</div>'
