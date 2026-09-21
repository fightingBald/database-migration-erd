"""Native D2 presentation settings; independent of schema parsing and rendering."""

from colorsys import hls_to_rgb
from dataclasses import dataclass
from hashlib import sha256

STYLES = ("clean", "classic")
COMPONENT_PADDING = 16
GRID_GAP = 48


@dataclass(frozen=True)
class GroupPalette:
    fill: str
    border: str
    header: str
    text: str


GROUP_PALETTES = {
    "blue": GroupPalette("#F5F8FD", "#B5CDEB", "#DFE9F5", "#244568"),
    "gold": GroupPalette("#FFFCF2", "#E5CE8B", "#FCEDBD", "#735713"),
    "green": GroupPalette("#F4FAF4", "#AFCCA5", "#DDEED5", "#315B2E"),
    "violet": GroupPalette("#F8F5FC", "#CDBBE4", "#E8DFF5", "#534272"),
    "slate": GroupPalette("#F5F6F8", "#BCC4CF", "#E4E8EE", "#334155"),
    "rose": GroupPalette("#FFF6F8", "#E3B5C3", "#F8DDE5", "#783E51"),
    "teal": GroupPalette("#F1FAF9", "#A6CFCA", "#D4EBE8", "#245C55"),
    "orange": GroupPalette("#FFF8F2", "#E3C1A1", "#FAE3CF", "#785230"),
}


def group_palette(key: str, color: str | None = None) -> GroupPalette:
    """Stable across processes and unrelated groups; labels also convey identity."""
    if color is not None:
        return GROUP_PALETTES[color]
    hue = int.from_bytes(sha256(key.encode()).digest()[:2], "big") / 65536

    def tint(lightness: float, saturation: float) -> str:
        return "#" + "".join(
            f"{round(c * 255):02X}" for c in hls_to_rgb(hue, lightness, saturation)
        )

    return GroupPalette(
        tint(0.975, 0.55), tint(0.78, 0.4), tint(0.90, 0.5), tint(0.28, 0.45)
    )


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
