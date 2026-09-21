"""Pure index descriptions shared by D2 output, sizing and verification."""

import html
import textwrap

from .schema import Index, Table

FOOTER_FONT_SIZE = 12
FOOTER_LINE_WIDTH = 44
FOOTER_STYLE = (
    f"text-align:left;font-size:{FOOTER_FONT_SIZE}px;"
    "color:#64748B;line-height:1.5;white-space:pre"
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


def index_footer(table: Table) -> str:
    """Wrap plain text without dropping SQL tokens or truncating identifiers.

    This becomes a native container label, not extra SQL-table rows. Keep the full
    unwrapped metadata in the table tooltip as well.
    """
    lines = []
    for index in sorted_indexes(table):
        label = "UNIQUE" if index.unique else "INDEX"
        name = f" {index.name}" if index.name else ""
        method = f" USING {index.method}" if index.method else ""
        description = f"{label}{name}{method} ({', '.join(index.columns)})"
        if index.where:
            description += f" WHERE {index.where}"
        lines.extend(
            textwrap.wrap(
                description,
                width=FOOTER_LINE_WIDTH,
                expand_tabs=False,
                replace_whitespace=False,
                drop_whitespace=False,
                break_on_hyphens=False,
            )
        )
    return "\n".join(lines)


def footer_markup(text: str) -> str:
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
    return f'<div data-erd-index-footer="true" style="{FOOTER_STYLE}">{content}</div>'
