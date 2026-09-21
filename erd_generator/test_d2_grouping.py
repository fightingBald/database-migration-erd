from itertools import combinations, pairwise

import pytest

from erd_generator.d2_grouping import centered_ranks, group_tables, layout_ranks
from erd_generator.validation import Relationship


def relation(source, target, columns=("parent_id",), refs=("id",)):
    return Relationship(source, columns, target, refs)


def related_graph(count=4, size=10):
    groups = tuple(
        tuple(f"table_{i * count + group:02}" for i in range(size))
        for group in range(count)
    )
    edges = []
    for names in groups:
        edges.extend(relation(name, names[0]) for name in names[1:])
        edges.extend(relation(names[i], names[i - 1]) for i in range(2, size))
    edges.extend(relation(groups[i][0], groups[i - 1][0]) for i in range(1, count))
    return (
        tuple(sorted(name for group in groups for name in group)),
        tuple(edges),
        groups,
    )


def test_forty_connected_tables_group_by_relationships_not_name_order():
    names, edges, expected = related_graph()
    assert group_tables(names, edges) == expected
    assert group_tables(tuple(reversed(names)), tuple(reversed(edges))) == expected


def test_common_identity_table_stays_outside_business_groups():
    names, edges, expected = related_graph()
    names = (*names, "shared_identity")
    edges = (*edges, *(relation(name, "shared_identity") for name in names[:-1]))
    groups = group_tables(names, edges)
    assert sorted(groups) == sorted((*expected, ("shared_identity",)))


def test_multiple_foreign_keys_composite_keys_and_self_links_do_not_bias_grouping():
    names, edges, expected = related_graph()
    extra = [
        relation(edge.table, edge.ref_table, ("x", "y"), ("a", "b")) for edge in edges
    ]
    extra.extend(relation(name, name) for name in names)
    assert group_tables(names, (*edges, *extra, *extra)) == expected


@pytest.mark.parametrize("count", [0, 1, 11, 40])
def test_empty_or_unconnected_input_has_no_artificial_groups(count):
    names = tuple(f"t{i:02}" for i in range(count))
    assert group_tables(names, ()) == ((names,) if names else ())


def test_small_related_graph_keeps_existing_layout():
    names, edges, _ = related_graph(count=2, size=5)
    assert group_tables(names, edges) == (names,)


@pytest.mark.parametrize("shape", ["clique", "star"])
def test_graph_without_distinct_communities_keeps_existing_layout(shape):
    names = tuple(f"t{i:02}" for i in range(20))
    pairs = (
        combinations(names, 2)
        if shape == "clique"
        else ((n, names[0]) for n in names[1:])
    )
    assert group_tables(names, tuple(relation(a, b) for a, b in pairs)) == (names,)


def test_layout_ranks_fold_a_chain_without_changing_relationships():
    names = tuple(f"t{i}" for i in range(10))
    pairs = tuple(pairwise(names))
    ranks = layout_ranks(names, pairs)
    assert len(set(ranks.values())) == 2
    assert all(ranks[a] != ranks[b] for a, b in pairs)
    assert ranks == layout_ranks(tuple(reversed(names)), tuple(reversed(pairs)))


@pytest.mark.parametrize("hub_count", [1, 2])
def test_shared_hubs_have_neighbors_on_both_sides_without_changing_edges(hub_count):
    hubs = tuple(f"hub_{i}" for i in range(hub_count))
    domains = ("a", "b", "c", "d")
    pairs = tuple((d, h) for d in domains for h in hubs) + tuple(pairwise(hubs))
    names = (*domains, *hubs)
    ranks = centered_ranks(names, pairs, hubs=hubs, weights={n: 1 for n in names})
    for hub in hubs:
        assert (
            min(ranks[d] for d in domains) < ranks[hub] < max(ranks[d] for d in domains)
        )
    assert all(ranks[a] != ranks[b] for a, b in pairs)
    assert ranks == centered_ranks(
        tuple(reversed(names)),
        tuple(reversed(pairs)),
        hubs=tuple(reversed(hubs)),
        weights={n: 1 for n in reversed(names)},
    )


def test_unconnected_neighbors_balance_by_size_around_hub():
    names = ("a", "b", "c", "d", "hub")
    pairs = tuple((n, "hub") for n in names[:-1])
    weights = dict(zip(names, (9, 3, 3, 3, 1), strict=True))
    ranks = centered_ranks(names, pairs, hubs=("hub",), weights=weights)
    assert ranks["a"] < ranks["hub"]
    assert all(ranks[n] > ranks["hub"] for n in ("b", "c", "d"))


def test_no_eligible_hubs_keeps_existing_layering():
    names = ("a", "b", "c")
    pairs = (("a", "b"), ("b", "c"))
    assert centered_ranks(names, pairs, hubs=names) == layout_ranks(names, pairs)


def test_business_hub_can_be_centered_without_an_explicit_singleton_candidate():
    names = ("books", "branches", "loans", "members")
    pairs = (("loans", "books"), ("loans", "branches"), ("loans", "members"))
    ranks = centered_ranks(names, pairs)
    assert min(ranks.values()) < ranks["loans"] < max(ranks.values())
    assert all(ranks[a] != ranks[b] for a, b in pairs)


def test_linked_outer_pair_does_not_push_all_independent_neighbors_to_one_side():
    names = (*"abcdefg", "hub")
    pairs = (*tuple((n, "hub") for n in "abcdef"), ("f", "g"))
    ranks = centered_ranks(names, pairs, hubs=("hub",))
    left = sum(rank < ranks["hub"] for rank in ranks.values())
    right = sum(rank > ranks["hub"] for rank in ranks.values())
    assert abs(left - right) <= 1
    assert all(ranks[a] != ranks[b] for a, b in pairs)
    assert ranks == centered_ranks(
        tuple(reversed(names)),
        (*tuple((b, a) for a, b in reversed(pairs)), *pairs, ("hub", "hub")),
        hubs=("hub",),
    )
