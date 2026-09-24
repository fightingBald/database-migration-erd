"""Cluster proximity must reflect real FK constraints, with bounded planning."""

import itertools
from collections import Counter

import pytest

from erd_generator.d2_affinity import (
    affinity_ranks,
    cluster_pairs,
    group_weights,
    packed_ranks,
    weighted_distance,
)
from erd_generator.validation import Relationship


def test_supernode_plan_uses_sizes_and_is_stable_without_mutating_inputs():
    sizes = {"a": (500, 1800), "b": (900, 350), "c": (600, 400), "d": (300, 200)}
    weights = {("a", "b"): 4, ("b", "c"): 1, ("c", "d"): 2}
    before = dict(sizes)
    result = packed_ranks(sizes, weights, "right")
    assert set(result) == set(sizes)
    assert len(set(result.values())) > 1
    assert result == packed_ranks(dict(reversed(list(sizes.items()))), weights, "right")
    assert sizes == before
    assert packed_ranks({}, {}, "right") == {}


def test_weights_count_constraints_once_without_inventing_relations():
    owners = {"a": "one", "a_notes": "one", "b": "two", "c": "three"}
    pair = Relationship("a", ("tenant", "b_id"), "b", ("tenant", "id"))
    relationships = (
        pair,
        Relationship(
            pair.table, pair.columns, pair.ref_table, pair.ref_columns, "duplicate"
        ),
        Relationship("a", ("other_b",), "b", ("id",)),
        Relationship("b", ("c_id",), "c", ("id",)),
        Relationship("a_notes", ("a_id",), "a", ("id",)),
        Relationship("b", ("parent_id",), "b", ("id",)),
    )
    expected = {("one", "two"): 2, ("three", "two"): 1}
    assert group_weights(owners, relationships) == expected
    assert group_weights(owners, tuple(reversed(relationships))) == expected


def test_pairing_optimizes_all_pairs_instead_of_greedily_taking_largest_edge():
    weights = {("a", "b"): 8, ("a", "c"): 7, ("b", "d"): 7, ("c", "d"): 1}
    hints = cluster_pairs(weights)
    assert hints == {"c": "a", "d": "b"}
    assert cluster_pairs(dict(reversed(list(weights.items())))) == hints
    assert sum(weights[tuple(sorted(pair))] for pair in hints.items()) == 14


@pytest.mark.parametrize("count", [0, 1, 6, 12, 30])
def test_pairing_is_deterministic_disjoint_and_uses_only_real_edges(count):
    names = [f"group_{i:02}" for i in range(count)]
    weights = {(a, b): 1 + i % 5 for i, (a, b) in enumerate(itertools.pairwise(names))}
    hints = cluster_pairs(weights)
    assert hints == cluster_pairs(dict(reversed(list(weights.items()))))
    counts = Counter(n for pair in hints.items() for n in pair)
    assert all(count == 1 for count in counts.values())
    assert all(tuple(sorted(pair)) in weights for pair in hints.items())


def test_shared_hub_remains_anchor_and_belongs_to_only_one_pair():
    weights = {tuple(sorted((name, "hub"))): i for i, name in enumerate("abcde", 1)}
    assert cluster_pairs(weights) == {"e": "hub"}


def test_weighted_ranks_put_strong_pairs_next_to_each_other_preserving_layers():
    ranks = {"a": 0, "a_peer": 0, "b": 1, "c": 2, "d": 3}
    weights = {("a", "c"): 10, ("b", "d"): 10, ("a", "b"): 1}
    result = affinity_ranks(ranks, weights)
    assert abs(result["a"] - result["c"]) == 1
    assert abs(result["b"] - result["d"]) == 1
    assert result["a"] == result["a_peer"]
    assert len(set(result.values())) == len(set(ranks.values()))
    assert result == affinity_ranks(dict(reversed(list(ranks.items()))), weights)
    assert ranks["c"] == 2


def test_ties_and_small_rank_sets_keep_existing_orientation():
    ranks = {"a": 0, "b": 1}
    assert affinity_ranks(ranks, {("a", "b"): 100}) == ranks
    assert affinity_ranks(ranks, {}) == ranks
    assert affinity_ranks({}, {}) == {}


def test_many_layers_use_bounded_search_without_reducing_affinity():
    ranks = {f"g{i:02}": i for i in range(20)}
    weights = {("g00", "g19"): 10, ("g02", "g17"): 5, ("g04", "g15"): 5}

    def cost(order):
        return sum(w * abs(order[a] - order[b]) for (a, b), w in weights.items())

    result = affinity_ranks(ranks, weights)
    assert cost(result) < cost(ranks)
    assert result == affinity_ranks(ranks, weights)
    assert sorted(result.values()) == sorted(ranks.values())


def test_distance_accounts_for_both_axes_and_all_relationship_weights():
    weights = {("a", "b"): 3, ("b", "c"): 1}
    centres = {"a": (0, 0), "b": (20, 10), "c": (20, 50)}
    assert weighted_distance(weights, centres) == 32.5
    assert weighted_distance({}, centres) == 0
