"""Pack already-rendered regions, keeping strongly related regions nearby."""

import math
from itertools import combinations

from .d2_layout import pack_sizes
from .diagram_routing import Rect

REGION_GAP = 120
CANVAS_PAD = 100


def pack_rectangles(
    sizes: dict[str, tuple[float, float]], weights: dict[tuple[str, str], int]
) -> dict[str, Rect]:
    if not sizes:
        return {}
    columns = [
        [key[0] for key in col]
        for col in pack_sizes([((k,), *v) for k, v in sorted(sizes.items())])
    ]

    def place(order):
        result = {}
        x = CANVAS_PAD
        for column in order:
            y = CANVAS_PAD
            for key in column:
                width, height = sizes[key]
                result[key] = Rect(x, y, width, height)
                y += height + REGION_GAP
            x += max(sizes[key][0] for key in column) + REGION_GAP
        return result

    area = sum(w * h for w, h in sizes.values())

    def score(order):
        boxes = place(order)
        width = max(r.right for r in boxes.values()) + CANVAS_PAD
        height = max(r.bottom for r in boxes.values()) + CANVAS_PAD
        distance = sum(
            weight
            * (
                abs(boxes[a].x + boxes[a].width / 2 - boxes[b].x - boxes[b].width / 2)
                + abs(
                    boxes[a].y + boxes[a].height / 2 - boxes[b].y - boxes[b].height / 2
                )
            )
            for (a, b), weight in weights.items()
        ) / max(1, sum(weights.values()))
        return (
            math.log(width * height / area)
            + 0.3 * abs(math.log(width / height / 1.4))
            + 0.4 * distance / math.sqrt(area)
        )

    # A bounded local search changes actual positions, never SQL membership.
    slots = [(i, j) for i, c in enumerate(columns) for j in range(len(c))]
    best = score(columns)
    for _ in range(min(4, len(sizes))):
        improved = None
        for (i, j), (a, b) in combinations(slots, 2):
            candidate = [c[:] for c in columns]
            candidate[i][j], candidate[a][b] = candidate[a][b], candidate[i][j]
            value = score(candidate)
            if value < best - 1e-9:
                best, improved = value, candidate
        if improved is None:
            break
        columns = improved
    return place(columns)
