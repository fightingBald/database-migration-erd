"""Native D2 presentation settings; independent of schema parsing and rendering."""

STYLES = ("clean", "classic")

# sql_table body text and key markers come from theme slots, while its fill
# controls both the header and row separators in the pinned D2 renderer.
CLEAN_CONFIG = (
    "    theme-overrides: {",
    '      N1: "#1E293B"',
    '      N2: "#64748B"',
    '      N3: "#CBD5E1"',
    '      N7: "#FFFFFF"',
    '      B1: "#64748B"',
    '      B2: "#334155"',
    '      AA2: "#0F766E"',
    "    }",
)

# Do not round sql_table corners: D2 0.7.1 can produce invalid clip-path XML
# for quoted qualified table names. Connection rounding does not use that path.
CLEAN_TABLE = (
    "  style: {",
    '    fill: "#DFE9F5"',
    '    stroke: "#FFFFFF"',
    '    font-color: "#17324D"',
    "    stroke-width: 1",
    "    font-size: 20",
    "  }",
)

CLEAN_CONNECTION = (
    "  style: {",
    '    stroke: "#64748B"',
    "    stroke-width: 2",
    "    border-radius: 14",
    '    font-color: "#475569"',
    "    font-size: 16",
    "    italic: false",
    "  }",
)
