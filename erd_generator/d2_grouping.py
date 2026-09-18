"""Deterministic relationship communities and compact layers, without renderer I/O."""

from collections import Counter

from .validation import Relationship

MIN_GROUPING_TABLES = 12
MIN_MODULARITY = 0.15


def group_tables(
    tables: tuple[str, ...], relationships: tuple[Relationship, ...]
) -> tuple[tuple[str, ...], ...]:
    """Find communities in one validated connected component.

    Each pair of tables contributes once, regardless of FK direction, composite
    key width or parallel FKs. Greedy positive modularity gains favour internal
    connectivity over links to the rest of the graph. Ties use sorted names.
    """
    names = tuple(sorted(tables))
    if not names:
        return ()
    fallback = (names,)
    if len(names) < MIN_GROUPING_TABLES:
        return fallback
    pairs = sorted(
        {
            tuple(sorted((fk.table, fk.ref_table)))
            for fk in relationships
            if fk.table != fk.ref_table
        }
    )
    if not pairs:
        return fallback
    degree = Counter(name for pair in pairs for name in pair)
    groups = {name: (name,) for name in names}
    totals = dict(degree)
    connections = dict.fromkeys(pairs, 1)
    edge_count = len(pairs)

    def gain(pair):
        a, b = pair
        # The common positive denominator 2*m*m can be omitted for comparison.
        return 2 * edge_count * connections[pair] - totals[a] * totals[b]

    while connections:
        a, b = min(connections, key=lambda pair: (-gain(pair), pair))
        if gain((a, b)) <= 0:
            break
        groups[a] = tuple(sorted((*groups[a], *groups.pop(b))))
        totals[a] += totals.pop(b)
        merged = Counter()
        for (left, right), weight in connections.items():
            left = a if left == b else left
            right = a if right == b else right
            if left != right:
                merged[tuple(sorted((left, right)))] += weight
        connections = dict(merged)

    if sum(len(group) >= 3 for group in groups.values()) < 2:
        return fallback
    owners = {name: key for key, group in groups.items() for name in group}
    internal = sum(owners[a] == owners[b] for a, b in pairs)
    modularity = internal / edge_count - sum(
        (sum(degree[name] for name in group) / (2 * edge_count)) ** 2
        for group in groups.values()
    )
    if modularity < MIN_MODULARITY:
        return fallback

    # Shared identity/tenant tables linked across several communities should not
    # acquire an arbitrary business grouping just because of a tie in merging.
    neighbors = {name: set() for name in names}
    for a, b in pairs:
        neighbors[a].add(b)
        neighbors[b].add(a)
    shared = {
        name
        for name in names
        if degree[name] >= 6
        and len({owners[other] for other in neighbors[name]}) >= 3
        and sum(owners[other] == owners[name] for other in neighbors[name])
        < degree[name] / 2
    }
    result = [
        tuple(name for name in group if name not in shared) for group in groups.values()
    ]
    result.extend((name,) for name in shared)
    return tuple(sorted(group for group in result if group))


def layout_ranks(
    names: tuple[str, ...], pairs: tuple[tuple[str, str], ...]
) -> dict[str, int]:
    """Color adjacent nodes into a few deterministic layout layers.

    These ranks orient layout input only. The emitter retains the actual FK
    arrow direction with D2's left- or right-pointing connection syntax.
    """
    neighbors = {name: set() for name in names}
    for a, b in pairs:
        if a != b:
            neighbors[a].add(b)
            neighbors[b].add(a)
    ranks = {}
    for name in sorted(names, key=lambda name: (-len(neighbors[name]), name)):
        used = {ranks[other] for other in neighbors[name] if other in ranks}
        ranks[name] = next(rank for rank in range(len(used) + 1) if rank not in used)
    return ranks


def centered_ranks(
    names: tuple[str, ...],
    pairs: tuple[tuple[str, str], ...],
    *,
    hubs: tuple[str, ...] = (),
    weights: dict[str, float] | None = None,
) -> dict[str, int]:
    """Put eligible shared units between their neighbors, without fixed coordinates.

    These ranks only orient D2 source order; arrowheads still encode the FK.
    Adjacent hubs receive separate ranks inside the central band. The remaining
    independent units or colour classes are balanced by estimated cross size.
    """
    neighbors = {name: set() for name in names}
    for a, b in pairs:
        if a != b:
            neighbors[a].add(b)
            neighbors[b].add(a)
    central = tuple(sorted(n for n in hubs if len(neighbors[n]) >= 3))
    remaining = tuple(sorted(set(names) - set(central)))
    if not central or len(remaining) < 2:
        return layout_ranks(names, pairs)
    weight = {n: (weights or {}).get(n, 1) for n in names}
    inner = layout_ranks(
        central, tuple((a, b) for a, b in pairs if a in central and b in central)
    )
    outer = layout_ranks(
        remaining,
        tuple((a, b) for a, b in pairs if a not in central and b not in central),
    )
    if len(set(outer.values())) == 1:
        loads = [0.0, 0.0]
        for name in sorted(remaining, key=lambda n: (-weight[n], n)):
            side = min(range(2), key=lambda i: (loads[i], i))
            outer[name] = side
            loads[side] += weight[name]
    classes = max(outer.values()) + 1
    pivot = min(
        range(1, classes),
        key=lambda p: (
            abs(sum(weight[n] * (1 if rank < p else -1) for n, rank in outer.items())),
            p,
        ),
    )
    span = max(inner.values()) + 1
    return {
        **{n: rank + (span if rank >= pivot else 0) for n, rank in outer.items()},
        **{n: pivot + rank for n, rank in inner.items()},
    }
