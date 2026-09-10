from copy import deepcopy

import pytest

from erd_generator.d2 import build_d2, quote_d2
from erd_generator.schema import Column, ForeignKey, Index, Table


def sample_schema():
    return {
        "public.parent": Table(
            "public.parent",
            columns=[Column("tenant", "INT"), Column("id", "INT")],
            primary_key={"tenant", "id"},
        ),
        "public.child": Table(
            "public.child",
            columns=[
                Column("tenant", "INT"),
                Column("parent_id", "INT"),
                Column("email", "TEXT"),
            ],
            primary_key={"tenant", "parent_id"},
            foreign_keys=[
                ForeignKey(
                    ("tenant", "parent_id"),
                    "public.parent",
                    ("tenant", "id"),
                    "fk_parent",
                )
            ],
        ),
    }


def test_sql_tables_and_composite_foreign_key_groups():
    source = build_d2(sample_schema(), show_types=True)
    assert "layout-engine: elk" in source
    assert "direction: right" in source
    assert source.count("shape: sql_table") == 2
    assert '"tenant": "INT" {constraint: [primary_key; foreign_key]}' in source
    assert (
        '"public.child"."tenant" -> "public.parent"."tenant": "fk_parent [1/2]"'
        in source
    )
    assert (
        '"public.child"."parent_id" -> "public.parent"."id": "fk_parent [2/2]"'
        in source
    )


def test_no_types_and_isolated_empty_table():
    source = build_d2(
        {"empty": Table("empty"), "one": Table("one", columns=[Column("id", "BIGINT")])}
    )
    assert '"id": ""' in source
    assert "BIGINT" not in source
    assert source.count("shape: sql_table") == 2


def test_unique_marker_does_not_overstate_composite_partial_or_expression_indexes():
    table = Table(
        "a",
        columns=[Column(name) for name in ("email", "tenant", "status", "name")],
        indexes=[
            Index("single", ("EMAIL",), column_names=("email",), unique=True),
            Index(
                "compound",
                ("TENANT", "STATUS"),
                column_names=("tenant", "status"),
                unique=True,
            ),
            Index(
                "partial",
                ("STATUS",),
                column_names=("status",),
                unique=True,
                where="status > 0",
            ),
            Index(
                "expression",
                ("lower(name)",),
                expression_columns=("lower(name)",),
                column_names=(None,),
                unique=True,
                method="BTREE",
            ),
        ],
    )
    source = build_d2({"a": table})
    assert source.count("constraint: unique") == 1
    assert '"email": "" {constraint: unique}' in source
    assert "compound" in source and "status > 0" in source and "BTREE" in source


def test_repeated_foreign_keys_are_deduplicated_and_input_is_not_mutated():
    schema = sample_schema()
    schema["public.child"].foreign_keys *= 2
    before = deepcopy(schema)
    source = build_d2(schema)
    assert source.count(' -> "public.parent"') == 2
    assert schema == before
    assert source == build_d2(dict(reversed(list(schema.items()))))


def test_notes_and_relations_are_independent_of_metadata_insertion_order():
    schema = sample_schema()
    table = schema["public.child"]
    table.indexes = [Index("b", ("email",)), Index("a", ("tenant",))]
    table.foreign_keys.append(ForeignKey(("email",), "public.child", ("email",)))
    expected = build_d2(schema)
    table.indexes.reverse()
    table.foreign_keys.reverse()
    assert build_d2(schema) == expected


def test_single_implicit_primary_key_and_self_reference():
    table = Table(
        "a",
        columns=[Column("id"), Column("manager")],
        primary_key={"id"},
        foreign_keys=[ForeignKey(("manager",), "a", ())],
    )
    source = build_d2({"a": table})
    assert '"a"."manager" -> "a"."id"' in source
    assert ': "manager → id"' in source
    assert not table.foreign_keys[0].ref_columns


@pytest.mark.parametrize(
    "value,expected",
    [
        ("shape", '"shape"'),
        ("public.a", '"public.a"'),
        ('x"; other -> node', '"x\\"; other -> node"'),
        ("${secret}", '"\\${secret}"'),
        ("one\\two\n三", '"one\\\\two\\n三"'),
    ],
)
def test_d2_literal_escaping(value, expected):
    assert quote_d2(value) == expected


@pytest.mark.parametrize("direction", ["left", "up", "down", "right"])
def test_direction(direction):
    assert f"direction: {direction}" in build_d2(sample_schema(), direction=direction)


@pytest.mark.parametrize("value", ["diagonal", "right\nx -> y"])
def test_rejects_invalid_direction(value):
    with pytest.raises(ValueError, match="direction"):
        build_d2(sample_schema(), direction=value)


def test_rejects_xml_invalid_control_characters():
    with pytest.raises(ValueError, match="control"):
        quote_d2("a\x00b")
