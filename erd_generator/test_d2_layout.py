from copy import deepcopy

import pytest

from erd_generator import d2_layout
from erd_generator.d2_grouping import layout_ranks
from erd_generator.d2_layout import connected_components, plan_layout
from erd_generator.schema import Column, ForeignKey, Table
from erd_generator.validation import validate_schema


def test_components_preserve_cycles_self_references_and_isolated_tables():
    schema = {
        name: Table(name, columns=[Column("id", "INT"), Column("parent", "INT")])
        for name in ("a", "b", "c", "self", "isolated")
    }
    for child, parent in (("a", "b"), ("b", "c"), ("c", "a"), ("self", "self")):
        schema[child].foreign_keys.append(ForeignKey(("parent",), parent, ("id",)))
    relationships = validate_schema(schema).relationships
    components = connected_components(schema, relationships)
    assert [component.tables for component in components] == [
        ("a", "b", "c"),
        ("isolated",),
        ("self",),
    ]
    assert sum(len(component.relationships) for component in components) == 4
    for component in components:
        assert all(
            fk.table in component.tables and fk.ref_table in component.tables
            for fk in component.relationships
        )


def test_layout_adapts_to_table_dimensions_and_has_no_empty_columns():
    tall = {
        f"t{i}": Table(f"t{i}", columns=[Column(f"f{j}", "INT") for j in range(20)])
        for i in range(8)
    }
    wide = {
        f"t{i}": Table(f"t{i}", columns=[Column("long_column_name_" * 6, "TEXT")])
        for i in range(8)
    }
    tall_layout = plan_layout(tall, (), show_types=True, direction="right")
    wide_layout = plan_layout(wide, (), show_types=True, direction="right")
    assert len(tall_layout) > len(wide_layout)
    for layout in (tall_layout, wide_layout):
        assert all(layout)
        names = [name for column in layout for group in column for name in group.tables]
        assert sorted(names) == sorted(tall)


def test_layout_keeps_a_connected_group_intact_and_does_not_mutate_inputs():
    schema = {f"t{i}": Table(f"t{i}", columns=[Column("id", "INT")]) for i in range(12)}
    schema["t0"].foreign_keys = [ForeignKey(("id",), "t1", ("id",))]
    relationships = validate_schema(schema).relationships
    before = deepcopy(schema)
    expected = plan_layout(schema, relationships, show_types=True, direction="down")
    assert expected == plan_layout(
        dict(reversed(list(schema.items()))),
        tuple(reversed(relationships)),
        show_types=True,
        direction="down",
    )
    assert schema == before
    assert any(group.tables == ("t0", "t1") for column in expected for group in column)


def test_business_membership_joins_disconnected_parts_without_inventing_edges():
    schema = {
        n: Table(n, columns=[Column("id", "INT")]) for n in ("a", "b", "c", "d", "e")
    }
    schema["b"].foreign_keys = [ForeignKey(("id",), "c", ("id",))]
    edges = validate_schema(schema).relationships
    layout = plan_layout(
        schema,
        edges,
        show_types=True,
        direction="right",
        keep_together=(("a", "b"), ("c", "d")),
    )
    blocks = [block for column in layout for block in column]
    assert sorted(block.tables for block in blocks) == [("a", "b", "c", "d"), ("e",)]
    assert tuple(f for block in blocks for f in block.relationships) == edges


@pytest.mark.parametrize("direction", ["right", "left", "up", "down"])
def test_table_layers_balance_a_star_without_mutating_schema(direction):
    schema = {
        name: Table(name, columns=[Column("id", "INT"), Column("root", "INT")])
        for name in ("hub", *(f"detail_{i}" for i in range(6)))
    }
    for name, value in schema.items():
        if name != "hub":
            value.foreign_keys = [ForeignKey(("root",), "hub", ("id",))]
    edges = validate_schema(schema).relationships
    part = d2_layout.Component(tuple(schema), edges)
    before = deepcopy(schema)
    ranks = d2_layout.table_ranks(part, schema, True, direction)
    assert sum(r < ranks["hub"] for r in ranks.values()) == 3
    assert sum(r > ranks["hub"] for r in ranks.values()) == 3
    assert ranks == d2_layout.table_ranks(
        d2_layout.Component(tuple(reversed(part.tables)), tuple(reversed(edges))),
        dict(reversed(list(schema.items()))),
        True,
        direction,
    )
    assert schema == before


@pytest.mark.parametrize("count", [0, 1, 6])
def test_table_layers_leave_unconnected_tables_alone(count):
    schema = {f"t{i}": Table(f"t{i}") for i in range(count)}
    ranks = d2_layout.table_ranks(
        d2_layout.Component(tuple(schema), ()), schema, False, "right"
    )
    assert ranks == layout_ranks(tuple(schema), ())


def test_table_layers_keep_existing_layout_when_a_tall_hub_would_only_add_width():
    schema = {
        n: Table(n, columns=[Column(f"f{i}", "TEXT") for i in range(fields)])
        for n, fields in (("hub", 40), *((f"t{i}", 2) for i in range(6)))
    }
    for name, value in schema.items():
        if name != "hub":
            value.foreign_keys = [ForeignKey(("f0",), "hub", ("f0",))]
    edges = validate_schema(schema).relationships
    part = d2_layout.Component(tuple(schema), edges)
    assert d2_layout.table_ranks(part, schema, True, "right") == layout_ranks(
        tuple(schema), tuple((f.table, f.ref_table) for f in edges)
    )
