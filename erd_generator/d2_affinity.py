"""Bounded, deterministic cluster planning from real foreign-key constraints."""

from collections import Counter
from functools import cache
from itertools import permutations

from .validation import Relationship


def group_weights(
    owners: dict[str, str], relationships: tuple[Relationship, ...]
) -> dict[tuple[str, str], int]:
    """Count constraints, not column arrows or duplicate constraint names."""
    weights: Counter[tuple[str, str]] = Counter()
    seen = set()
    for fk in relationships:
        identity = (fk.table, fk.columns, fk.ref_table, fk.ref_columns)
        a, b = owners[fk.table], owners[fk.ref_table]
        if a != b and identity not in seen:
            weights[tuple(sorted((a, b)))] += 1
        seen.add(identity)
    return dict(sorted(weights.items()))


def affinity_ranks(
    ranks: dict[str, int], weights: dict[tuple[str, str], int]
) -> dict[str, int]:
    """Reorder existing layers without splitting them or adding layout edges."""
    original = tuple(sorted(set(ranks.values())))
    if len(original) < 3 or not weights:
        return dict(ranks)
    edges: Counter[tuple[int, int]] = Counter()
    for (a, b), weight in weights.items():
        if ranks[a] != ranks[b]:
            edges[tuple(sorted((ranks[a], ranks[b])))] += weight

    def score(order):
        positions = {rank: i for i, rank in enumerate(order)}
        return (
            sum(w * abs(positions[a] - positions[b]) for (a, b), w in edges.items()),
            sum(a != b for a, b in zip(order, original, strict=True)),
            order,
        )

    best = original
    if len(original) <= 7:
        best = min(permutations(original), key=score)
    else:
        # Bounded local search, even for hundreds of clusters. Strict cost
        # improvements avoid oscillation; ties preserve the existing layout.
        for _ in range(8):
            neighbors = [
                (*best[:i], best[i + 1], best[i], *best[i + 2 :])
                for i in range(len(best) - 1)
            ]
            candidate = min(neighbors, key=score)
            if score(candidate)[0] >= score(best)[0]:
                break
            best = candidate
    if score(best)[0] >= score(original)[0]:
        return dict(ranks)
    positions = dict(zip(best, original, strict=True))
    return {name: positions[rank] for name, rank in ranks.items()}


def cluster_pairs(weights: dict[tuple[str, str], int]) -> dict[str, str]:
    """Disjoint pairs: exact small matching, bounded greedy large matching.

    Put each pair's more connected cluster first. Every pair uses an existing
    relationship; a shared hub can join only one pair, not absorb every region.
    """
    strength: Counter[str] = Counter()
    for (a, b), weight in weights.items():
        strength[a] += weight
        strength[b] += weight
    names = tuple(sorted(strength))
    if len(names) <= 12:

        @cache
        def match(mask):
            if not mask:
                return 0, ()
            i = (mask & -mask).bit_length() - 1
            remaining = mask ^ (1 << i)
            best_score, best_pairs = match(remaining)
            for j in range(i + 1, len(names)):
                pair = names[i], names[j]
                if not remaining & (1 << j) or pair not in weights:
                    continue
                score, pairs = match(remaining ^ (1 << j))
                score, pairs = score + weights[pair], (pair, *pairs)
                if score > best_score or (score == best_score and pairs < best_pairs):
                    best_score, best_pairs = score, pairs
            return best_score, best_pairs

        _, pairs = match((1 << len(names)) - 1)
    else:
        used, pairs = set(), []
        for (a, b), _ in sorted(weights.items(), key=lambda p: (-p[1], p[0])):
            if a not in used and b not in used:
                pairs.append((a, b))
                used.update((a, b))
    result = {}
    for pair in pairs:
        anchor, child = sorted(pair, key=lambda n: (-strength[n], n))
        result[child] = anchor
    return dict(sorted(result.items()))


def weighted_distance(
    weights: dict[tuple[str, str], int], centres: dict[str, tuple[float, float]]
) -> float:
    """Mean Manhattan cluster-centre distance, weighted by FK constraints."""
    return (
        sum(
            w * sum(abs(x - y) for x, y in zip(centres[a], centres[b], strict=True))
            for (a, b), w in weights.items()
        )
        / sum(weights.values())
        if weights
        else 0
    )
