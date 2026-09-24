"""Deterministic orthogonal routing around measured diagram obstacles."""

import heapq
from dataclasses import dataclass
from functools import cache
from itertools import pairwise

Point = tuple[float, float]
CROSSING_COST = 400


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def padded(self, gap: float) -> "Rect":
        return Rect(
            self.x - gap, self.y - gap, self.width + 2 * gap, self.height + 2 * gap
        )

    def inside(self, point: Point) -> bool:
        x, y = point
        return self.x < x < self.right and self.y < y < self.bottom


def segment_clear(a: Point, b: Point, obstacles: list[Rect]) -> bool:
    if a[0] == b[0]:
        low, high = sorted((a[1], b[1]))
        return not any(
            r.x < a[0] < r.right and low < r.bottom and high > r.y for r in obstacles
        )
    if a[1] == b[1]:
        low, high = sorted((a[0], b[0]))
        return not any(
            r.y < a[1] < r.bottom and low < r.right and high > r.x for r in obstacles
        )
    return False


def simplify(points: list[Point]) -> list[Point]:
    result = []
    for p in points:
        if result and p == result[-1]:
            continue
        while len(result) >= 2 and (
            result[-2][0] == result[-1][0] == p[0]
            or result[-2][1] == result[-1][1] == p[1]
        ):
            result.pop()
        result.append(p)
    return result


def path_length(points: list[Point]) -> float:
    return sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in pairwise(points))


def crossing_cost(a: Point, b: Point, occupied: list[list[Point]]) -> float:
    count = 0
    for line in occupied:
        for c, d in pairwise(line):
            if a[1] == b[1] and c[0] == d[0] and c[1] != d[1]:
                count += min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(
                    c[1], d[1]
                ) < a[1] < max(c[1], d[1])
            elif a[0] == b[0] and c[1] == d[1] and c[0] != d[0]:
                count += min(a[1], b[1]) <= c[1] <= max(a[1], b[1]) and min(
                    c[0], d[0]
                ) < a[0] < max(c[0], d[0])
    return count * CROSSING_COST


def route(
    start: Point,
    end: Point,
    obstacles: list[Rect],
    *,
    occupied: list[list[Point]] | None = None,
    max_length: float | None = None,
) -> list[Point]:
    """A* on obstacle boundaries, with a bend cost and no diagonal shortcuts.

    Coordinates come from measured bounds rather than pixels. Interior points
    are forbidden; boundaries are safe because callers already pad obstacles.
    """
    if any(r.inside(start) or r.inside(end) for r in obstacles):
        raise ValueError("blocked endpoint")
    if (
        max_length is not None
        and abs(start[0] - end[0]) + abs(start[1] - end[1]) > max_length
    ):
        raise ValueError("no obstacle-free route")
    occupied = occupied or []
    if segment_clear(start, end, obstacles) and not crossing_cost(start, end, occupied):
        return [start, end]
    xs = sorted({start[0], end[0], *(v for r in obstacles for v in (r.x, r.right))})
    ys = sorted({start[1], end[1], *(v for r in obstacles for v in (r.y, r.bottom))})
    xs = [xs[0] - 24, *xs, xs[-1] + 24]
    ys = [ys[0] - 24, *ys, ys[-1] + 24]
    origin = (xs.index(start[0]), ys.index(start[1]), 0, 0.0)
    target = (xs.index(end[0]), ys.index(end[1]))
    costs = {origin: 0.0}
    labels = {origin[:3]: [(0.0, 0.0)]}
    previous = {}
    queue = [(0.0, 0.0, origin)]

    @cache
    def clear(x, y, nx, ny):
        return segment_clear((xs[x], ys[y]), (xs[nx], ys[ny]), obstacles)

    @cache
    def crossing(x, y, nx, ny):
        return crossing_cost((xs[x], ys[y]), (xs[nx], ys[ny]), occupied)

    while queue:
        _, cost, state = heapq.heappop(queue)
        if cost != costs[state]:
            continue
        x, y, heading, walked = state
        if (x, y) == target:
            points = [(xs[x], ys[y])]
            while state in previous:
                state = previous[state]
                points.append((xs[state[0]], ys[state[1]]))
            return simplify(points[::-1])
        for nx, ny, axis in (
            (x - 1, y, 1),
            (x + 1, y, 1),
            (x, y - 1, 2),
            (x, y + 1, 2),
        ):
            if not (0 <= nx < len(xs) and 0 <= ny < len(ys)) or not clear(x, y, nx, ny):
                continue
            step = abs(xs[nx] - xs[x]) + abs(ys[ny] - ys[y])
            length = walked + step
            distance = abs(xs[nx] - end[0]) + abs(ys[ny] - end[1])
            if max_length is not None and length + distance > max_length:
                continue
            value = (
                cost
                + step
                + (24 if heading and heading != axis else 0)
                + crossing(x, y, nx, ny)
            )
            node = (nx, ny, axis)
            existing = labels.get(node, [])
            if any(
                c <= value and (max_length is None or d <= length) for d, c in existing
            ):
                continue
            labels[node] = [
                (d, c)
                for d, c in existing
                if c < value or (max_length is not None and d < length)
            ] + [(length, value)]
            neighbor = (*node, length)
            costs[neighbor] = value
            previous[neighbor] = state
            heapq.heappush(queue, (value + distance, value, neighbor))
    raise ValueError("no obstacle-free route")
