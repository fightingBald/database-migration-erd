import pytest

from erd_generator.d2 import build_d2
from erd_generator.schema import Column, ForeignKey, Table


@pytest.mark.parametrize(
    "fk,message",
    [
        (ForeignKey(("id",), "missing", ("id",)), "unknown target table"),
        (ForeignKey(("missing",), "b", ("id",)), "unknown source column"),
        (ForeignKey(("id",), "b", ("missing",)), "unknown target column"),
        (ForeignKey(("id",), "b", ("id", "tenant")), "column counts"),
        (ForeignKey(("id",), "b", ()), "implicit composite"),
        (ForeignKey((), "b", ()), "empty foreign key"),
    ],
)
def test_invalid_foreign_keys_are_rejected_before_generating_nodes(fk, message):
    schema = {
        "a": Table("a", columns=[Column("id")], foreign_keys=[fk]),
        "b": Table(
            "b", columns=[Column("id"), Column("tenant")], primary_key={"id", "tenant"}
        ),
    }
    with pytest.raises(ValueError, match=message):
        build_d2(schema)


@pytest.mark.parametrize(
    "schema,message",
    [
        ({}, "no tables"),
        ({"a": Table("wrong")}, "table key"),
        ({"a": Table("a", columns=[Column("id"), Column("id")])}, "duplicate column"),
        ({"a": Table("a", primary_key={"missing"})}, "primary key"),
    ],
)
def test_invalid_schema(schema, message):
    with pytest.raises(ValueError, match=message):
        build_d2(schema)


def test_cycles_are_valid():
    schema = {
        name: Table(
            name,
            columns=[Column("id")],
            foreign_keys=[ForeignKey(("id",), target, ("id",))],
        )
        for name, target in (("a", "b"), ("b", "a"))
    }
    assert build_d2(schema).count('" -> "') == 2
