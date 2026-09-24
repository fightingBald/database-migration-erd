"""Cross-group references belong to the referring field, not to a routed bend."""

from copy import deepcopy

import pytest

from erd_generator.d2 import build_d2, quote_d2
from erd_generator.layout_config import GroupRule, LayoutConfig
from erd_generator.schema import Column, ForeignKey, Table
from erd_generator.sql_parser import parse_schema_from_sql
from tests.support import FIXTURES


def reference_schema():
    schema = {
        "public.entry": Table(
            "public.entry",
            columns=[Column(n, "INT") for n in ("tenant", "item_id", "local_id")],
            primary_key={"tenant"},
            foreign_keys=[
                ForeignKey(("tenant", "item_id"), "public.item", ("tenant", "id")),
                ForeignKey(("local_id",), "public.local", ("id",)),
                ForeignKey(("tenant",), "public.entry", ("tenant",)),
            ],
        ),
        "public.item": Table(
            "public.item", columns=[Column("tenant", "INT"), Column("id", "INT")]
        ),
        "public.local": Table("public.local", columns=[Column("id", "INT")]),
    }
    config = LayoutConfig(
        (
            GroupRule("entries", ("public.entry", "public.local")),
            GroupRule("items", ("public.item",)),
        )
    )
    return schema, config


@pytest.mark.parametrize("style", ["clean", "classic"])
@pytest.mark.parametrize("show_types", [False, True])
def test_optional_references_keep_fields_types_keys_arrows_and_input(style, show_types):
    schema, config = reference_schema()
    before = deepcopy(schema)
    options = dict(layout_config=config, show_types=show_types, style=style)
    plain = build_d2(schema, **options)
    source = build_d2(schema, show_references=True, **options)
    data_type = "INT" if show_types else ""
    assert "FK →" not in plain
    assert (
        f'"tenant": "{data_type}" {{constraint: [primary_key; "FK → item.tenant"]}}'
        in source
    )
    assert f'"item_id": "{data_type}" {{constraint: "FK → item.id"}}' in source
    assert f'"local_id": "{data_type}" {{constraint: foreign_key}}' in source
    assert source.count("FK →") == 2

    def edges(text):
        return [line for line in text.splitlines() if " -> " in line or " <- " in line]

    assert edges(source) == edges(plain)
    assert schema == before
    assert source == build_d2(
        dict(reversed(list(schema.items()))), show_references=True, **options
    )


def test_schema_qualification_disambiguates_same_named_targets_and_deduplicates_labels():
    schema, config = reference_schema()
    schema["archive.item"] = Table("archive.item", columns=[Column("id", "INT")])
    schema["public.entry"].foreign_keys += [
        ForeignKey(("item_id",), "archive.item", ("id",)),
        ForeignKey(("item_id",), "archive.item", ("id",), "another_constraint"),
    ]
    source = build_d2(schema, show_references=True, layout_config=config)
    assert '"FK → archive.item.id, public.item.id"' in source
    assert '"FK → public.item.tenant"' in source


def test_nested_communities_in_one_business_group_do_not_get_reference_labels():
    schema = {}
    parse_schema_from_sql(
        (FIXTURES / "related_tables.sql").read_text(),
        schema,
    )
    config = LayoutConfig((GroupRule("whole", tuple(schema)),))
    source = build_d2(schema, show_references=True, layout_config=config)
    assert source.count('label: ""') > 1  # Still has inferred inner communities.
    assert "FK →" not in source


def test_grouping_none_only_labels_explicit_group_boundaries():
    schema, config = reference_schema()
    assert "FK →" not in build_d2(schema, grouping="none", show_references=True)
    assert "FK → item.id" in build_d2(
        schema, grouping="none", show_references=True, layout_config=config
    )


def test_automatic_business_groups_label_only_cross_group_fields():
    schema = {
        f"{prefix}{suffix}": Table(
            f"{prefix}{suffix}",
            columns=[Column("id", "INT"), Column("parent_id", "INT")],
        )
        for prefix in ("books", "loans")
        for suffix in ("", "_details", "_history")
    }
    schema["loans"].foreign_keys = [ForeignKey(("parent_id",), "books", ("id",))]
    schema["loans_details"].foreign_keys = [
        ForeignKey(("parent_id",), "loans", ("id",))
    ]
    source = build_d2(schema, show_references=True)
    assert source.count("FK →") == 1
    assert '"FK → books.id"' in source


def test_reference_labels_quote_unusual_names_without_d2_substitution():
    name, key = '${literal}"\\表', 'id.${key}"\\值'
    schema = {
        "entry": Table(
            "entry",
            columns=[Column("ref", "INT")],
            foreign_keys=[ForeignKey(("ref",), name, (key,))],
        ),
        name: Table(name, columns=[Column(key, "INT")]),
    }
    config = LayoutConfig((GroupRule("one", ("entry",)), GroupRule("two", (name,))))
    source = build_d2(schema, show_references=True, layout_config=config)
    assert quote_d2(f"FK → {name}.{key}") in source


def test_empty_and_unrelated_schemas_do_not_add_references():
    with pytest.raises(ValueError, match="no tables"):
        build_d2({}, show_references=True)
    schema = {n: Table(n, columns=[Column("id", "INT")]) for n in ("one", "two")}
    assert build_d2(schema, show_references=True) == build_d2(schema)
    schema["one"].foreign_keys = [ForeignKey(("missing",), "two", ("id",))]
    with pytest.raises(ValueError, match="Schema validation failed"):
        build_d2(schema, show_references=True)
