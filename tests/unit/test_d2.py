import re
from copy import deepcopy

import pytest

from erd_generator.d2 import build_d2, quote_d2
from erd_generator.layout_config import GroupRule, LayoutConfig
from erd_generator.schema import Column, ForeignKey, Index, Table
from erd_generator.sql_parser import parse_schema_from_sql
from tests.support import FIXTURES
from tests.support.schemas import related_schema


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


@pytest.mark.parametrize("packed", [False, True])
@pytest.mark.parametrize("mode", ["ordered", "paired"])
@pytest.mark.parametrize("engine", ["elk", "tala"])
def test_cluster_candidates_are_deterministic_and_preserve_schema(packed, mode, engine):
    schema = sample_schema()
    schema["other"] = Table(
        "other",
        columns=[Column("id", "INT")],
        foreign_keys=[ForeignKey(("id",), "public.parent", ("id",))],
    )
    if packed:
        schema["isolated"] = Table("isolated", columns=[Column("id", "INT")])
    config = LayoutConfig(tuple(GroupRule(n, (n,)) for n in schema))
    before = deepcopy(schema)
    options = dict(layout_config=config, layout_engine=engine)
    baseline = build_d2(schema, **options)
    candidate = build_d2(schema, cluster_affinity=mode, **options)
    assert candidate.count(" -> ") + candidate.count(" <- ") == baseline.count(
        " -> "
    ) + baseline.count(" <- ")
    assert candidate.count("shape: sql_table") == len(schema)
    assert candidate == build_d2(
        dict(reversed(list(schema.items()))), cluster_affinity=mode, **options
    )
    assert build_d2(
        schema, grouping="none", cluster_affinity=mode, **options
    ) == build_d2(schema, grouping="none", **options)
    assert schema == before


def test_elk_affinity_only_reorders_top_level_cluster_ranks(monkeypatch):
    from erd_generator import d2

    schema = sample_schema()
    config = LayoutConfig(tuple(GroupRule(n, (n,)) for n in schema))
    calls = []

    def reorder(ranks, weights):
        calls.append((ranks, weights))
        return ranks

    monkeypatch.setattr(d2, "affinity_ranks", reorder)
    options = dict(layout_config=config)
    assert build_d2(schema, cluster_affinity="ordered", **options) == build_d2(
        schema, **options
    )
    assert len(calls) == 2  # Declaration order and ELK layer order, only at the root.
    assert all(
        len(ranks) == 2 and list(weights.values()) == [1] for ranks, weights in calls
    )


def test_invalid_affinity_mode_fails_before_source_generation():
    with pytest.raises(ValueError, match="cluster affinity"):
        build_d2(sample_schema(), cluster_affinity="unknown")


@pytest.mark.parametrize("engine", ["elk", "tala"])
def test_affinity_order_places_strong_pairs_next_in_declarations(engine):
    schema = {
        n: Table(n, columns=[Column(c, "INT") for c in ("id", "ref1", "ref2")])
        for n in "abcd"
    }
    for a, b in (("a", "c"), ("b", "d")):
        schema[a].foreign_keys.extend(
            ForeignKey((c,), b, ("id",)) for c in ("ref1", "ref2")
        )
    schema["a"].foreign_keys.append(ForeignKey(("id",), "b", ("id",)))
    config = LayoutConfig(tuple(GroupRule(n, (n,)) for n in schema))
    source = build_d2(
        schema, layout_engine=engine, layout_config=config, cluster_affinity="ordered"
    )
    order = re.findall(r'^  label: "([abcd])"$', source, re.MULTILINE)
    assert abs(order.index("a") - order.index("c")) == 1
    assert abs(order.index("b") - order.index("d")) == 1
    assert source.count("shape: sql_table") == 4


@pytest.mark.parametrize("engine", ["elk", "tala"])
def test_nested_affinity_preserves_business_regions_and_rewrites_field_paths(engine):
    schema = sample_schema()
    config = LayoutConfig(tuple(GroupRule(n, (n,)) for n in schema))
    source = build_d2(
        schema, layout_engine=engine, layout_config=config, cluster_affinity="paired"
    )
    assert '_erd_pair_0: {\n  label: ""' in source
    assert source.count("shape: sql_table") == 2
    assert source.count("label.near: top-left") == 2
    arrows = [
        line
        for line in source.splitlines()
        if re.match(r"_erd_pair_0\..+ (?:->|<-) ", line)
    ]
    assert len(arrows) == 2
    assert all(line.count("_erd_pair_0.") == 2 for line in arrows)


def test_automatic_business_regions_have_labels_and_colours_without_configuration():
    schema = {
        f"{p}_{s}": Table(f"{p}_{s}", columns=[Column("id", "INT")])
        for p in ("books", "loans", "members")
        for s in ("details", "files", "links")
    }
    before = deepcopy(schema)
    source = build_d2(schema)
    assert (
        'label: "Books"' in source
        and 'label: "Loans"' in source
        and 'label: "Members"' in source
    )
    assert source.count("label.near: top-left") == 3
    assert source.count("shape: sql_table") == 9
    assert source.count("grid-rows:") >= 4
    assert "label.near: top-left" not in build_d2(schema, grouping="none")
    assert schema == before


def test_configuration_can_group_disconnected_tables_and_preserve_cross_group_fk_metadata():
    schema = sample_schema()
    schema["extra"] = Table("extra", columns=[Column("id")])
    config = LayoutConfig(
        (
            GroupRule("local", ("public.child", "extra"), "Local ${literal}", "gold"),
            GroupRule("remote", ("public.parent",), "Remote", "green"),
        )
    )
    source = build_d2(schema, layout_config=config)
    assert source.count("shape: sql_table") == 3
    assert 'label: "Local \\${literal}"' in source
    assert 'label: "Remote"' in source
    assert "constraint: [primary_key; foreign_key]" in source
    assert "FK: (tenant, parent_id)" not in source  # Preserve the named constraint.
    assert "fk_parent: (tenant, parent_id)" in source
    assert "fk_parent [1/2]" in source and "fk_parent [2/2]" in source
    assert (
        "grid-rows:" not in source
    )  # The connected business regions share native ELK routing.


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


@pytest.mark.parametrize("engine", ["elk", "tala"])
def test_layout_engine_is_embedded_without_changing_schema_semantics(engine):
    schema = sample_schema()
    before = deepcopy(schema)
    source = build_d2(schema, layout_engine=engine, show_types=True)
    assert f"layout-engine: {engine}" in source
    assert source.count("shape: sql_table") == 2
    assert '"public.child"."tenant" -> "public.parent"."tenant"' in source
    assert '"public.child"."parent_id" -> "public.parent"."id"' in source
    assert schema == before


@pytest.mark.parametrize("engine", ["dagre", "tala\nx -> y", ""])
def test_invalid_layout_engine_is_rejected_before_source_generation(engine):
    with pytest.raises(ValueError, match="layout engine"):
        build_d2(sample_schema(), layout_engine=engine)


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


def test_clean_and_classic_keep_column_definitions_and_relationship_endpoints():
    schema = sample_schema()
    before = deepcopy(schema)
    clean = build_d2(schema, show_types=True)
    classic = build_d2(schema, show_types=True, style="classic")
    assert "theme-overrides:" in clean
    assert "theme-overrides:" not in classic

    def columns(text):
        return [line for line in text.splitlines() if line.startswith('  "')]

    def edges(text):
        return [
            line.removesuffix(" {")
            for line in text.splitlines()
            if line.startswith('"') and " -> " in line
        ]

    assert columns(clean) == columns(classic)
    assert edges(clean) == edges(classic)
    assert schema == before


@pytest.mark.parametrize("style", ["unknown", "clean\na -> b"])
def test_rejects_invalid_style(style):
    with pytest.raises(ValueError, match="style"):
        build_d2(sample_schema(), style=style)


def test_rejects_invalid_python_layout_configuration():
    with pytest.raises(ValueError, match="Layout config"):
        build_d2(sample_schema(), layout_config={})


def test_large_explicit_business_regions_retain_internal_relationship_communities():
    schema = {}
    parse_schema_from_sql(
        (FIXTURES / "related_tables.sql").read_text(),
        schema,
    )
    left = tuple(n for n in schema if int(n[-2:]) % 4 < 2)
    right = tuple(n for n in schema if n not in left)
    config = LayoutConfig((GroupRule("left", left), GroupRule("right", right)))
    source = build_d2(schema, layout_config=config)
    assert source.count("label.near: top-left") == 2
    assert source.count('label: ""') == 4
    assert source.count("shape: sql_table") == 40


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


def test_disconnected_layout_is_deterministic_and_preserves_schema():
    schema = sample_schema()
    schema.update(
        {
            name: Table(name, columns=[Column("id", "INT")])
            for name in (
                "_erd_column_0",
                "_erd_component_0",
                'public."quoted"',
                "孤立表",
            )
        }
    )
    before = deepcopy(schema)
    source = build_d2(schema, show_types=True)
    assert "grid-columns:" in source
    assert source == build_d2(dict(reversed(list(schema.items()))), show_types=True)
    assert schema == before
    assert source.count("shape: sql_table") == len(schema)
    assert source.count(" -> ") == 3  # Two composite edges and the FK tooltip.
    for name in schema:
        assert f"{quote_d2(name)}: {{" in source


def test_one_connected_component_keeps_native_elk_source():
    source = build_d2(sample_schema())
    assert "grid-columns:" not in source
    assert '"public.child"."tenant" -> "public.parent"."tenant"' in source


def test_large_connected_graph_groups_automatically_with_an_explicit_rollback():
    schema = {}
    fixture = FIXTURES / "related_tables.sql"
    parse_schema_from_sql(fixture.read_text(), schema)
    before = deepcopy(schema)
    grouped = build_d2(schema, show_types=True)
    assert grouped.count('  label: ""') == 4
    assert grouped.count("shape: sql_table") == 40
    assert "grid-columns:" not in grouped
    assert " <- " in grouped
    assert grouped == build_d2(dict(reversed(list(schema.items()))), show_types=True)
    flat = build_d2(schema, show_types=True, grouping="none")
    assert "_erd_group_" not in flat
    assert flat.count("shape: sql_table") == 40
    assert " <- " not in flat
    assert schema == before


def test_tala_retains_automatic_groups_without_elk_arrow_reordering():
    schema = {}
    fixture = FIXTURES / "related_tables.sql"
    parse_schema_from_sql(fixture.read_text(), schema)
    elk = build_d2(schema)
    tala = build_d2(schema, layout_engine="tala")
    assert " <- " in elk and " <- " not in tala
    assert tala.count('  label: ""') == elk.count('  label: ""')
    assert tala.count("shape: sql_table") == len(schema)
    assert tala == build_d2(dict(reversed(list(schema.items()))), layout_engine="tala")


def test_invalid_grouping_is_rejected():
    with pytest.raises(ValueError, match="grouping"):
        build_d2(sample_schema(), grouping="unknown")


def test_invalid_layout_strategy_is_rejected():
    with pytest.raises(ValueError, match="strategy"):
        build_d2(sample_schema(), layout_strategy="unknown")


def test_compact_candidate_keeps_business_membership_and_input_unchanged():
    schema = related_schema()
    original = deepcopy(schema)
    config = LayoutConfig((GroupRule("one", tuple(schema), "One"),))
    baseline = build_d2(schema, layout_config=config)
    compact = build_d2(schema, layout_config=config, layout_strategy="compact")
    assert 'label: "One"' in compact
    assert compact.count("shape: sql_table") == len(schema)
    assert "_erd_group_0: {" in baseline
    assert "_erd_group_0: {" not in compact
    assert schema == original
    assert compact == build_d2(
        dict(reversed(list(schema.items()))),
        layout_config=config,
        layout_strategy="compact",
    )
